# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import sys
import time
from dataclasses import asdict
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import median
from typing import Iterable
from urllib.parse import parse_qs, quote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from gaokao_decision.database import (
    connect,
    fetch_admissions,
    fetch_score_ranks,
    import_records,
    import_score_rank_records,
    init_db,
    list_batches,
)
from gaokao_decision.importer import load_admissions, load_score_ranks
from gaokao_decision.importer import ambiguous_stable_option_keys, option_group_key
from gaokao_decision.commercial import (
    APP_VERSION as SERVER_APP_VERSION,
    project_root_from,
    system_info_payload,
)
from gaokao_decision.models import CandidateProfile
from gaokao_decision.plan import build_volunteer_plan_from_recommendations
from gaokao_decision.rank_conversion import build_score_band_plan


APP_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>志愿参考系统</title>
  <style>
    :root {
      --ink: #1f251f;
      --muted: #777368;
      --line: #ded6c7;
      --line-strong: #c9bda8;
      --paper: #f5f1e8;
      --panel: rgba(255, 255, 252, 0.94);
      --accent: #1f6f4c;
      --accent-dark: #155238;
      --danger: #c74747;
      --warn: #c59230;
      --steady: #d2ac49;
      --safe: #4f8b62;
      --gold: #caa767;
      --gold-soft: #f4ead6;
      --graphite: #2f332f;
      --shadow: 0 18px 44px rgba(92, 75, 44, 0.11);
      --shadow-soft: 0 8px 24px rgba(92, 75, 44, 0.07);
      --radius: 10px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: linear-gradient(180deg, #fffefa 0%, #f7f2e8 52%, #eee4d4 100%);
      font-family: ui-serif, "Songti SC", "STSong", "Noto Serif CJK SC", "PingFang SC", "Microsoft YaHei", serif;
      line-height: 1.5;
    }
    .shell { max-width: 1660px; margin: 0 auto; padding: 22px 34px 24px; }
    header {
      display: grid;
      grid-template-columns: auto minmax(260px, 1fr) auto;
      gap: 24px;
      align-items: flex-end;
      padding: 0 0 17px;
      border-bottom: 1px solid rgba(201, 189, 168, 0.84);
    }
    h1 { margin: 0; color: #1d241f; font-size: 31px; font-weight: 800; letter-spacing: 0; }
    h2 { margin: 0 0 13px; font-size: 19px; font-weight: 780; letter-spacing: 0; }
    h3 { margin: 0 0 10px; font-size: 15px; font-weight: 760; letter-spacing: 0; }
    .subtle, .mini { color: var(--muted); }
    .subtle {
      margin-top: 4px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 13px;
    }
    .mini {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 13px;
      min-width: 260px;
    }
    .brand-logo {
      width: 51px;
      height: 51px;
      flex: 0 0 auto;
      display: block;
      filter: drop-shadow(0 12px 20px rgba(24, 93, 64, 0.2));
    }
    .brand-logo svg {
      width: 100%;
      height: 100%;
      display: block;
    }
    .brand h1 {
      font-family: "FZYaoti", "STZhongsong", "Noto Serif CJK SC", "Microsoft YaHei UI", "Songti SC", serif;
      font-size: 23px;
      font-weight: 700;
      line-height: 1.05;
      letter-spacing: 0;
    }
    .brand-en {
      margin-top: 4px;
      color: #8a806c;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 11px;
      letter-spacing: 0.08em;
    }
    .data-brief {
      display: flex;
      min-width: 0;
      max-width: 100%;
      align-items: center;
      gap: 9px;
      padding: 0;
      flex-wrap: wrap;
      overflow: visible;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 15px;
      font-weight: 760;
      color: #3e413a;
    }
    .data-brief .mini { font-weight: 600; color: #8b806e; }
    .data-brief .stamp {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      white-space: nowrap;
    }
    .data-brief .calc-value {
      white-space: nowrap;
    }
    .header-actions {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: flex-end;
      gap: 6px;
      min-width: 0;
    }
    .header-action-row {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 9px;
      flex-wrap: wrap;
    }
    .header-warning {
      max-width: 560px;
      margin: 0;
      color: var(--danger);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 11px;
      font-weight: 800;
      line-height: 1.35;
      text-align: right;
    }
    .data-updated-chip {
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      padding: 3px 10px;
      border: 1px solid #d9c8a9;
      border-radius: 999px;
      background: #fffaf0;
      color: #6a5b43;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }
    .user-chip {
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      padding: 0 10px;
      border: 1px solid #d9c8a9;
      border-radius: 999px;
      background: #fffaf0;
      color: var(--accent);
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }
    .header-actions button {
      width: auto;
      height: 38px;
      padding: 0 11px;
      border: 1px solid transparent;
      background: transparent;
      color: #5f5b51;
      text-align: center;
      box-shadow: none;
      font-size: 13px;
      font-weight: 700;
    }
    .header-actions button:hover {
      background: #fbf6e9;
      border-color: var(--line);
      color: var(--accent);
    }
    .stamp {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 28px;
      padding: 4px 10px;
      border: 1px solid #d9caa8;
      border-radius: 999px;
      background: rgba(255, 255, 252, 0.72);
      color: #83745a;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
      font-weight: 700;
    }
    .stamp.danger {
      border-color: #efb5b5;
      background: #fff1ef;
      color: var(--danger);
    }
    .stamp.warn {
      border-color: #edcf96;
      background: #fff7df;
      color: #9a681a;
    }
    .notice {
      margin: 14px 0;
      padding: 11px 14px;
      background: rgba(255, 248, 235, 0.82);
      border: 1px solid #e5cfa4;
      color: #68410d;
      border-radius: var(--radius);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 13px;
      box-shadow: var(--shadow-soft);
    }
    .notice p { margin: 0; }
    .notice p + p { margin-top: 6px; }
    .reference-warning {
      color: var(--danger);
      font-weight: 850;
    }
    .controls {
      position: relative;
      display: grid;
      grid-template-columns: minmax(90px, 0.46fr) minmax(118px, 0.58fr) minmax(214px, 1.05fr) minmax(52px, 0.23fr) minmax(420px, 1.7fr);
      gap: 0;
      align-items: end;
      margin: 12px 0 14px;
      padding: 10px 12px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      box-shadow: var(--shadow);
      overflow: visible;
    }
    .controls.has-dirty-note {
      padding-top: 24px;
    }
    label {
      display: grid;
      gap: 7px;
      color: #4d4c45;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
      font-weight: 650;
    }
    .controls > label {
      min-height: 56px;
      padding: 0 8px;
      border-right: 1px solid rgba(222, 214, 199, 0.88);
      grid-template-rows: 17px auto;
      align-content: center;
      gap: 5px;
      font-size: 11px;
    }
    .controls > label:first-child { padding-left: 0; }
    .controls > label:nth-of-type(4) { border-right: 0; }
    .controls > label.interest-control { grid-template-rows: 21px auto; }
    .controls > label:first-child input {
      height: 38px;
      padding: 0;
      border: 0;
      background: transparent;
      color: #1d231f;
      font-family: ui-serif, "Songti SC", "STSong", serif;
      font-size: 28px;
      font-weight: 780;
    }
    .controls > label:first-child input::placeholder {
      color: #9a9387;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 13px;
      font-weight: 700;
    }
    .settings-toggle-row {
      grid-column: 1 / -1;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      align-items: stretch;
      margin-top: 15px;
    }
    .settings-toggle-row > details {
      min-width: 0;
      min-height: 28px;
      display: block;
    }
    .settings-toggle-row > details[open] {
      min-height: 172px;
      max-height: 172px;
      overflow: auto;
    }
    .profile-panel {
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(250, 247, 239, 0.75);
      padding: 4px 7px;
      text-align: left;
    }
    .settings-toggle-row summary {
      min-height: 24px;
      display: grid;
      grid-template-columns: auto auto minmax(0, 1fr);
      align-items: center;
      gap: 6px;
      list-style: none;
      color: var(--accent);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 13px;
      font-weight: 850;
      line-height: 1.2;
      text-align: left;
      cursor: pointer;
    }
    .settings-toggle-row summary::-webkit-details-marker { display: none; }
    .settings-toggle-row summary::before {
      content: ">";
      grid-column: 1;
      justify-self: start;
      color: #72806f;
      font-size: 12px;
      font-weight: 900;
    }
    .settings-toggle-row > details[open] > summary::before {
      transform: rotate(90deg);
    }
    .settings-toggle-row .summary-title {
      grid-column: 2;
      justify-self: start;
      white-space: nowrap;
    }
    .strategy-summary-note,
    .filter-summary-note {
      grid-column: 3;
      justify-self: start;
      min-width: 0;
      max-width: 100%;
      overflow: hidden;
      color: #72706a;
      font-size: 10.5px;
      font-weight: 680;
      line-height: 1.25;
      text-align: left;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .custom-plan-hidden { display: none; }
    .profile-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 4px;
      margin-top: 4px;
      align-items: end;
      text-align: left;
    }
    .profile-grid label {
      gap: 4px;
      font-size: 10px;
    }
    .profile-grid input,
    .profile-grid select {
      height: 30px;
      padding: 0 7px;
      font-size: 11px;
    }
    .profile-grid .wide-field {
      grid-column: span 2;
    }
    .checkline {
      display: flex;
      align-items: center;
      gap: 6px;
      min-height: 30px;
      padding: 5px 7px;
      border: 1px solid rgba(222, 214, 199, 0.76);
      border-radius: 7px;
      background: rgba(255, 253, 247, 0.7);
      font-weight: 600;
    }
    .checkline input { width: 15px; height: 15px; accent-color: var(--accent); }
    .dirty-banner {
      grid-column: 1 / -1;
      display: none;
      margin-top: 12px;
      padding: 9px 12px;
      border: 1px solid #efc6bf;
      border-radius: var(--radius);
      background: #fff3ef;
      color: var(--danger);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 13px;
      font-weight: 760;
    }
    .dirty-banner.open { display: block; }
    .label-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    input, select, button {
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: rgba(255, 255, 252, 0.84);
      color: var(--ink);
      padding: 0 11px;
      font: inherit;
      letter-spacing: 0;
    }
    input:focus, select:focus, button:focus-visible {
      outline: 2px solid rgba(31, 111, 76, 0.18);
      outline-offset: 2px;
      border-color: #91b79e;
    }
    button {
      background: linear-gradient(180deg, #247b55, #155f40);
      border-color: var(--accent);
      color: #fff;
      cursor: pointer;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-weight: 760;
    }
    button:hover { background: linear-gradient(180deg, #1d6c4a, #114a32); }
    .controls > button[type="submit"] {
      height: 50px;
      align-self: center;
      margin-left: 18px;
      border-color: #174f36;
      border-radius: 8px;
      background: linear-gradient(180deg, #196a49 0%, #0f4b32 100%);
      box-shadow: 0 12px 24px rgba(31, 111, 76, 0.21);
    }
    .choice-button {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      background: #f9fbf5;
      border-color: #bfd2c3;
      color: var(--ink);
      font-weight: 650;
      text-align: left;
    }
    .choice-button:hover { background: #edf6ed; }
    .choice-button::after { content: "管理"; color: var(--accent); font-size: 12px; font-weight: 760; }
    .controls .choice-button {
      height: 32px;
      padding: 0 7px;
      border-radius: 6px;
      font-size: 11px;
    }
    .controls .choice-button::after { font-size: 11px; }
    .dialog-backdrop {
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 18px;
      background: rgba(38, 33, 25, 0.42);
      z-index: 80;
      backdrop-filter: blur(5px);
    }
    .dialog-backdrop.open { display: flex; }
    .dialog {
      width: min(520px, 100%);
      max-height: calc(100vh - 36px);
      display: flex;
      flex-direction: column;
      background: #fffef9;
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: 0 24px 90px rgba(42, 34, 22, 0.28);
      overflow: hidden;
    }
    .dialog-head, .dialog-actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 15px 18px;
      border-bottom: 1px solid var(--line);
      background: #fbf8f0;
    }
    .dialog-actions {
      border-top: 1px solid var(--line);
      border-bottom: 0;
      justify-content: flex-end;
      flex-wrap: wrap;
    }
    .dialog-actions button {
      width: auto;
      min-width: 108px;
      padding: 0 14px;
      white-space: nowrap;
      flex: 0 0 auto;
    }
    .agreement-box {
      display: grid;
      gap: 8px;
    }
    #infoDialog.startup-agreement-dialog .dialog {
      max-height: calc(100vh - 24px);
    }
    #infoDialog.startup-agreement-dialog .dialog-head {
      padding: 11px 16px;
    }
    #infoDialog.startup-agreement-dialog .dialog-body {
      padding: 12px 16px 14px;
    }
    #infoDialog.startup-agreement-dialog .agreement-box p {
      margin: 0;
      font-size: 13px;
      line-height: 1.36;
    }
    #infoDialog.startup-agreement-dialog .agreement-box p + p {
      margin-top: 4px;
    }
    .agreement-checkline {
      display: flex;
      align-items: flex-start;
      gap: 9px;
      padding: 8px 10px;
      border: 1px solid #d9caa8;
      border-radius: 8px;
      background: #fffaf0;
      color: #4d4c45;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 13px;
      font-weight: 760;
      line-height: 1.36;
      cursor: pointer;
    }
    .agreement-checkline input {
      width: 18px;
      height: 18px;
      margin-top: 1px;
      padding: 0;
      flex: 0 0 auto;
      accent-color: var(--accent);
    }
    .agreement-actions {
      display: flex;
      justify-content: flex-end;
      gap: 9px;
      flex-wrap: wrap;
      margin-top: 0;
    }
    .agreement-actions button {
      width: auto;
      min-width: 118px;
      height: 36px;
      padding: 0 13px;
      white-space: nowrap;
    }
    .cancel-page {
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
      background: linear-gradient(180deg, #fffefa 0%, #f7f2e8 100%);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }
    .cancel-panel {
      width: min(520px, 100%);
      padding: 22px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fffef9;
      box-shadow: var(--shadow);
      text-align: left;
    }
    .cancel-panel h1 {
      margin: 0 0 9px;
      font-size: 22px;
      font-weight: 850;
    }
    .cancel-panel p {
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }
    .cancel-panel button {
      width: auto;
      min-width: 108px;
      height: 36px;
      padding: 0 13px;
    }
    .dialog-body { padding: 18px; overflow: auto; }
    .interest-picker-dialog .dialog {
      width: min(860px, calc(100vw - 36px));
      height: min(82vh, 720px);
    }
    .interest-picker-dialog .dialog-body {
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
      scrollbar-gutter: stable;
    }
    .interest-picker-dialog .tag-groups {
      max-height: none;
      overflow: visible;
      padding-right: 8px;
    }
    .report-preview-dialog .dialog {
      width: min(1120px, calc(100vw - 32px));
      height: min(86vh, 860px);
    }
    .report-preview-dialog .dialog-body {
      flex: 1 1 auto;
      min-height: 0;
      padding: 0;
      background: #fff;
    }
    .report-preview-frame {
      display: block;
      width: 100%;
      height: 100%;
      border: 0;
      background: #fff;
    }
    .data-source-workbench-backdrop {
      position: fixed;
      inset: 0;
      display: none;
      background: rgba(37, 32, 24, 0.34);
      z-index: 86;
      backdrop-filter: blur(2px);
    }
    .data-source-workbench-backdrop.open { display: block; }
    .data-source-workbench {
      position: fixed;
      inset: 10px 14px;
      z-index: 92;
      width: auto;
      min-width: 0;
      max-width: none;
      height: auto;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fffef9;
      box-shadow: 0 24px 90px rgba(42, 34, 22, 0.28);
      overflow: hidden;
      opacity: 0;
      pointer-events: none;
      transform: translateY(10px) scale(0.985);
      transition: opacity .16s ease, transform .16s ease;
    }
    .data-source-workbench.open {
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0) scale(1);
    }
    .data-source-workbench-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
      padding: 14px 20px 10px;
      border-bottom: 1px solid rgba(222, 214, 199, 0.86);
      background: #fbf8f0;
    }
    .data-source-workbench-head h2 {
      margin: 0 0 4px;
      font-size: 20px;
      font-weight: 850;
    }
    .data-source-workbench-head button {
      width: 34px;
      min-width: 34px;
      height: 34px;
      padding: 0;
      border-radius: 999px;
      font-size: 18px;
      line-height: 1;
    }
    .data-source-workbench-body {
      min-height: 0;
      overflow: auto;
      padding: 12px 18px;
      background: #fbf8f0;
    }
    .data-source-workbench-footer {
      min-height: 30px;
      display: flex;
      align-items: center;
      padding: 6px 20px;
      border-top: 1px solid rgba(222, 214, 199, 0.86);
      background: #fffdf7;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .subject-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .subject-option {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 42px;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      cursor: pointer;
      background: #fbf8f0;
      color: var(--ink);
      font-size: 14px;
    }
    .subject-option input { width: 18px; height: 18px; accent-color: var(--accent); }
    .subject-option.selected {
      border-color: #95bfa1;
      background: #edf6ed;
      box-shadow: inset 0 0 0 1px rgba(31, 111, 76, 0.08);
    }
    .secondary-button {
      width: auto;
      min-width: 86px;
      background: #fffdf7;
      border-color: var(--line);
      color: var(--graphite);
    }
    .secondary-button:hover { background: #f7f0df; border-color: #c8b991; color: var(--graphite); }
    .secondary-button.primary-action {
      background: #edf6ed;
      border-color: #9fc0a9;
      color: var(--accent);
    }
    .secondary-button.primary-action:hover {
      background: #e0f0e2;
      border-color: #7da98a;
      color: #123f2b;
    }
    .danger-text-button {
      color: var(--danger);
      border-color: #efc6bf;
    }
    .danger-text-button:hover {
      background: #fff3ef;
      color: var(--danger);
    }
    .inline-button {
      width: auto;
      height: 24px;
      padding: 0 7px;
      border-color: #b9ceb9;
      background: #edf6ed;
      color: var(--accent);
      font-size: 11px;
      font-weight: 760;
    }
    .inline-button:hover { background: #dfeee0; }
    .tag-field {
      min-height: 32px;
      height: 32px;
      padding: 3px 7px;
      display: flex;
      align-items: center;
      justify-content: flex-start;
      flex-wrap: nowrap;
      gap: 5px;
      overflow: hidden;
      background: #f9fbf5;
      border-color: #bfd2c3;
      color: var(--ink);
      font-weight: 650;
      text-align: left;
    }
    .tag-field:hover { background: #edf6ed; }
    .tag-field::after {
      content: "编辑";
      margin-left: auto;
      color: var(--accent);
      font-size: 11px;
      font-weight: 760;
      flex: 0 0 auto;
    }
    .tag-chip {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 2px 7px;
      border: 1px solid #c9dccd;
      border-radius: 999px;
      background: #edf6ed;
      color: var(--accent);
      font-size: 12px;
      font-weight: 760;
      line-height: 1.4;
      white-space: nowrap;
      flex: 0 0 auto;
    }
    .tag-placeholder { color: var(--muted); font-size: 13px; }
    .tag-toolbar {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      margin-bottom: 12px;
    }
    .tag-groups {
      display: grid;
      gap: 12px;
      max-height: min(56vh, 560px);
      overflow: auto;
      padding-right: 4px;
    }
    .tag-group {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fbf8f0;
    }
    .tag-options {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .tag-option {
      width: auto;
      min-height: 32px;
      height: auto;
      padding: 5px 10px;
      border-color: var(--line);
      background: #fffdf7;
      color: var(--ink);
      font-size: 13px;
      font-weight: 650;
      white-space: normal;
      line-height: 1.35;
      display: inline-grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 7px;
      max-width: 100%;
      text-align: left;
    }
    .tag-option:hover { background: #f7f0df; }
    .tag-option.selected {
      background: #edf6ed;
      color: var(--accent);
      border-color: #95bfa1;
    }
    .tag-option .tag-main {
      display: grid;
      gap: 1px;
      min-width: 0;
    }
    .tag-option .tag-main b {
      min-width: 0;
      overflow-wrap: anywhere;
      word-break: break-word;
      font-size: 12px;
      line-height: 1.25;
    }
    .tag-option .tag-main small {
      color: #817866;
      font-size: 10px;
      font-weight: 700;
      line-height: 1.2;
      overflow-wrap: anywhere;
    }
    .tag-source-badge {
      align-self: start;
      padding: 1px 5px;
      border-radius: 999px;
      background: #f4ead6;
      color: #725d31;
      font-size: 10px;
      font-weight: 850;
      white-space: nowrap;
    }
    .tag-source-badge.admission {
      background: #e9f3ec;
      color: #1f6f4c;
    }
    .error-text { color: var(--danger); font-size: 13px; min-height: 20px; margin-top: 10px; }
    .data-source-manager {
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr);
      gap: 8px;
      height: 100%;
      min-height: 100%;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }
    .data-source-help {
      position: relative;
      justify-self: end;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf7;
    }
    .data-source-help summary {
      min-height: 32px;
      display: flex;
      align-items: center;
      gap: 7px;
      padding: 5px 10px;
      color: var(--accent);
      font-size: 12px;
      font-weight: 850;
      cursor: pointer;
      list-style: none;
    }
    .data-source-help summary::-webkit-details-marker { display: none; }
    .data-source-help summary::before {
      content: ">";
      color: #72806f;
      font-size: 12px;
      font-weight: 900;
      transition: transform .16s ease;
    }
    .data-source-help[open] summary::before {
      transform: rotate(90deg);
    }
    .data-source-help .notice {
      position: absolute;
      top: calc(100% + 8px);
      right: 0;
      z-index: 8;
      width: min(760px, calc(100vw - 82px));
      margin: 0;
      border-width: 1px;
      border-radius: 8px;
      box-shadow: none;
      overflow-wrap: anywhere;
    }
    .data-year-toolbar {
      display: grid;
      grid-template-columns: minmax(190px, 0.38fr) minmax(0, 1fr) auto auto;
      gap: 10px;
      align-items: center;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf7;
    }
    .data-year-toolbar label {
      display: grid;
      grid-template-columns: auto minmax(120px, 1fr);
      gap: 8px;
      align-items: center;
      color: #5d533f;
      font-size: 12px;
      font-weight: 850;
    }
    .data-year-toolbar select {
      min-width: 0;
      width: 100%;
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fffdf7;
      color: var(--ink);
      padding: 5px 8px;
      font-size: 12px;
    }
    .data-year-summary {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .data-year-summary b {
      color: var(--accent);
      font-size: 15px;
      font-weight: 900;
    }
    .data-year-progress {
      height: 7px;
      margin-top: 5px;
      overflow: hidden;
      border-radius: 999px;
      border: 1px solid #d6c8ae;
      background: #f4ead6;
    }
    .data-year-progress span {
      display: block;
      height: 100%;
      border-radius: inherit;
      background: #1f6f4c;
    }
    .data-year-missing {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      margin-top: 5px;
      padding: 2px 7px;
      border: 1px solid #e7c27d;
      border-radius: 999px;
      background: #fff7df;
      color: #7a5514;
      font-size: 11px;
      font-weight: 820;
    }
    .data-source-tabs {
      display: flex;
      gap: 6px;
      align-items: center;
      padding: 4px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf7;
      overflow-x: auto;
    }
    .data-source-tab {
      width: auto;
      min-width: 116px;
      height: 34px;
      padding: 0 14px;
      border-color: transparent;
      background: transparent;
      color: #5d533f;
      box-shadow: none;
      font-size: 12px;
      font-weight: 850;
      white-space: nowrap;
    }
    .data-source-tab:hover {
      border-color: #d9caa8;
      background: #fbf6e9;
      color: var(--accent);
    }
    .data-source-tab.is-active {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    .data-source-layout {
      display: block;
      height: 100%;
      min-height: 0;
      overflow: hidden;
    }
    .data-source-panel {
      min-width: 0;
      min-height: 0;
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr);
      gap: 10px;
      align-content: start;
      overflow: hidden;
    }
    .data-source-panel,
    .data-source-import-panel,
    .data-record-panel {
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf7;
      min-height: 0;
    }
    .data-source-import-panel {
      display: grid;
      gap: 10px;
      align-content: start;
      overflow: auto;
    }
    .data-source-tab-panel {
      display: none !important;
      height: 100%;
      min-height: 0;
    }
    .data-source-tab-panel.is-active {
      display: grid !important;
    }
    .data-panel-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      color: #38372f;
      font-size: 13px;
      font-weight: 880;
    }
    .data-panel-title span {
      color: var(--muted);
      font-size: 11px;
      font-weight: 760;
    }
    .year-add-wrap {
      position: relative;
      display: inline-flex;
      align-items: center;
    }
    .year-add-button {
      width: auto;
      min-width: 92px;
      height: 34px;
      padding: 0 10px;
      font-size: 12px;
    }
    .year-add-popover {
      position: absolute;
      top: calc(100% + 8px);
      right: 0;
      width: 280px;
      display: none;
      z-index: 4;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffef9;
      box-shadow: 0 18px 48px rgba(42, 34, 22, 0.18);
    }
    .year-add-popover.open { display: grid; gap: 9px; }
    .year-add-popover h3 {
      margin: 0;
      font-size: 14px;
    }
    .year-add-popover label {
      display: grid;
      gap: 4px;
      color: #5d533f;
      font-size: 11px;
      font-weight: 820;
    }
    .year-add-popover input,
    .year-add-popover select {
      min-width: 0;
      width: 100%;
      height: 32px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fffdf7;
      color: var(--ink);
      padding: 5px 8px;
      font-size: 12px;
    }
    .year-add-popover .checkline {
      display: flex;
      grid-template-columns: none;
      align-items: center;
      gap: 7px;
      font-size: 12px;
      font-weight: 760;
    }
    .year-add-popover .checkline input {
      width: 16px;
      height: 16px;
      padding: 0;
      accent-color: var(--accent);
    }
    .year-add-actions {
      display: flex;
      justify-content: flex-end;
      gap: 7px;
    }
    .year-add-actions button {
      width: auto;
      min-width: 72px;
      height: 32px;
      padding: 0 10px;
      font-size: 12px;
    }
    .data-source-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      align-items: center;
    }
    .data-source-actions select,
    .data-source-actions input[type="text"],
    .data-source-actions input[type="number"],
    .data-source-actions input[type="file"] {
      min-width: 0;
      width: 100%;
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fffdf7;
      color: var(--ink);
      padding: 5px 8px;
      font-size: 12px;
    }
    .data-source-actions input[type="file"] { grid-column: 1 / -1; }
    .data-source-actions button { width: 100%; }
    .data-source-import-panel .data-source-actions {
      grid-template-columns: minmax(180px, 0.9fr) minmax(110px, 0.5fr) minmax(180px, 0.9fr) minmax(260px, 1.2fr) minmax(130px, 0.55fr);
    }
    .data-source-import-panel .data-source-actions input[type="file"] { grid-column: auto; }
    .data-validation-list {
      display: grid;
      gap: 7px;
      margin: 0;
      padding: 10px;
      border: 1px solid #e8decb;
      border-radius: 8px;
      background: #fbf8f0;
      list-style: none;
      color: #5d533f;
      font-size: 12px;
      font-weight: 720;
    }
    .data-validation-list li::before {
      content: "✓";
      display: inline-grid;
      place-items: center;
      width: 16px;
      height: 16px;
      margin-right: 6px;
      border-radius: 999px;
      background: #edf6ed;
      color: var(--accent);
      font-size: 11px;
      font-weight: 900;
    }
    .template-links {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .template-links a {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 9px;
      border: 1px solid #b9ceb9;
      border-radius: 6px;
      background: #edf6ed;
      color: var(--accent);
      font-size: 12px;
      font-weight: 760;
      text-decoration: none;
    }
    .data-source-status {
      min-height: 18px;
      color: var(--muted);
      font-size: 12px;
    }
    .data-source-table-wrap {
      max-height: min(54vh, 560px);
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf7;
    }
    .data-source-panel .data-source-table-wrap {
      max-height: none;
      min-height: 0;
    }
    .data-source-table {
      width: 100%;
      table-layout: fixed;
      border-collapse: collapse;
      font-size: 12px;
    }
    .data-source-table th:nth-child(1),
    .data-source-table td:nth-child(1) { width: 36%; }
    .data-source-table th:nth-child(2),
    .data-source-table td:nth-child(2) { width: 18%; }
    .data-source-table th:nth-child(3),
    .data-source-table td:nth-child(3) { width: 26%; }
    .data-source-table th:nth-child(4),
    .data-source-table td:nth-child(4) { width: 20%; }
    .data-source-table th,
    .data-source-table td {
      padding: 8px;
      border-bottom: 1px solid #eee4d4;
      vertical-align: top;
      text-align: left;
    }
    .data-source-table th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #f8f1e3;
      color: #5d533f;
      font-size: 11px;
      font-weight: 850;
    }
    .data-source-table td {
      overflow-wrap: anywhere;
    }
    .data-source-table td:last-child > div:first-child {
      display: flex !important;
      align-items: center !important;
      gap: 5px !important;
      flex-wrap: wrap !important;
    }
    .data-source-table .secondary-button,
    .data-source-table .inline-button {
      width: auto;
      min-width: 0;
      min-height: 28px;
      height: auto;
      padding: 4px 8px;
      font-size: 11px;
      line-height: 1.2;
      white-space: normal;
      overflow-wrap: anywhere;
    }
    .data-source-table .source-name {
      font-weight: 800;
      color: var(--ink);
    }
    .data-source-table tr.is-active td {
      background: #edf6ed;
    }
    .source-chip {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 2px 7px;
      background: #f4ead6;
      color: #725d31;
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
    }
    .source-chip.uploaded {
      background: #e9f3ec;
      color: var(--accent);
    }
    .data-record-panel {
      min-width: 0;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr) auto;
      gap: 8px;
    }
    .data-record-panel #dataRecordStatus {
      max-width: min(760px, 70%);
      overflow: hidden;
      text-align: right;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .data-record-toolbar {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto;
      gap: 8px;
      align-items: center;
    }
    .data-record-toolbar input {
      min-width: 0;
      width: 100%;
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fffdf7;
      color: var(--ink);
      padding: 5px 8px;
      font-size: 12px;
    }
    .data-record-list-wrap {
      min-height: 0;
      max-height: none;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf7;
    }
    .data-record-list-head {
      position: sticky;
      top: 0;
      z-index: 1;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 8px 10px;
      border-bottom: 1px solid #eee4d4;
      background: #f8f1e3;
      color: #5d533f;
      font-size: 11px;
      font-weight: 850;
    }
    .data-record-list {
      display: grid;
      gap: 10px;
      padding: 10px;
    }
    .data-record-card {
      display: grid;
      gap: 10px;
      padding: 10px;
      border: 1px solid #eee4d4;
      border-radius: 8px;
      background: #fffefb;
      box-shadow: 0 6px 18px rgba(92, 75, 44, 0.05);
    }
    .data-record-card-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding-bottom: 8px;
      border-bottom: 1px solid #f0e7d7;
    }
    .data-record-card-head b {
      min-width: 0;
      color: #38372f;
      font-size: 13px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .data-record-card-head button {
      width: auto;
      min-width: 82px;
      height: 32px;
      padding: 0 12px;
      flex: 0 0 auto;
    }
    .data-record-field-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 10px;
    }
    .data-record-field {
      min-width: 0;
      display: grid;
      gap: 4px;
      align-content: start;
    }
    .data-record-field span {
      color: #776b57;
      font-size: 11px;
      font-weight: 850;
      line-height: 1.25;
    }
    .data-record-input,
    .data-record-textarea {
      width: 100%;
      min-width: 0;
      height: 30px;
      border: 1px solid #d9cdb9;
      border-radius: 6px;
      background: #fffefb;
      color: var(--ink);
      padding: 4px 7px;
      font-size: 12px;
      line-height: 1.35;
    }
    .data-record-textarea {
      min-height: 58px;
      height: 58px;
      resize: vertical;
    }
    .data-record-input[readonly],
    .data-record-textarea[readonly] {
      background: #f2eee6;
      color: #817866;
    }
    .data-record-pager {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
    }
    .data-record-pager .pager-actions {
      display: inline-flex;
      gap: 6px;
      align-items: center;
    }
    @media (max-width: 1360px) {
      .data-source-workbench-body {
        padding-inline: 18px;
      }
      .data-source-import-panel .data-source-actions {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .data-source-import-panel .data-source-actions input[type="file"] { grid-column: 1 / -1; }
    }
    @media (max-width: 1180px) {
      .data-source-workbench {
        inset: 0;
        border-radius: 0;
      }
      .data-year-toolbar {
        grid-template-columns: 1fr;
      }
      .year-add-popover {
        left: 0;
        right: auto;
        width: min(280px, calc(100vw - 42px));
      }
      .data-source-tab {
        min-width: 104px;
      }
      .data-record-field-grid {
        grid-template-columns: minmax(0, 1fr);
      }
    }
    .question-list {
      display: grid;
      gap: 12px;
      max-height: min(58vh, 620px);
      overflow: auto;
      padding-right: 4px;
    }
    .question {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbf8f0;
    }
    .question p { margin: 0 0 10px; font-size: 14px; }
    .scale {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 6px;
    }
    .scale button {
      height: 34px;
      padding: 0 6px;
      background: #fffdf7;
      color: var(--ink);
      border-color: var(--line);
      font-size: 12px;
      font-weight: 600;
    }
    .scale button.active {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }
    .result-box {
      display: none;
      margin-top: 14px;
      padding: 12px;
      border: 1px solid #bdd7c0;
      background: #edf6ed;
      border-radius: var(--radius);
    }
    .result-box.open { display: block; }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      grid-template-areas: "main";
      gap: 18px;
      align-items: start;
      min-width: 0;
    }
    .grid.cart-pinned {
      grid-template-columns: minmax(0, 1fr) 342px;
      grid-template-areas: "main aside";
    }
    main {
      grid-area: main;
      display: grid;
      gap: 14px;
      min-width: 0;
      max-width: 100%;
    }
    aside, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: var(--shadow);
      min-width: 0;
      max-width: 100%;
    }
    aside {
      grid-area: aside;
      display: none;
      padding: 18px;
      position: static;
      overflow: hidden;
    }
    .grid.cart-pinned aside {
      display: block;
    }
    .panel { margin-bottom: 0; overflow: hidden; }
    .panel > .panel-body { padding: 16px; }
    .step-panel[data-step-panel="2"] > .panel-body {
      padding-top: 10px;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 12px;
      background: #fbf8f0;
    }
    .metric b {
      display: block;
      color: var(--accent);
      font-family: ui-serif, "Songti SC", "STSong", serif;
      font-size: 22px;
      line-height: 1.1;
    }
    .bar {
      display: grid;
      grid-template-columns: 78px 1fr 38px;
      gap: 8px;
      align-items: center;
      margin: 9px 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
    }
    .track { height: 7px; background: #e5dfd3; border-radius: 999px; overflow: hidden; }
    .fill { height: 100%; border-radius: inherit; }
    .risk-高冲 { background: var(--danger); }
    .risk-冲 { background: #e99942; }
    .risk-稳中偏冲 { background: #d4a437; }
    .risk-稳 { background: var(--steady); }
    .risk-保 { background: var(--safe); }
    .risk-强保 { background: #7e6aa6; }
    .risk-证据不足 { background: #8a877e; }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 13px;
    }
    th, td {
      padding: 11px 12px;
      border-bottom: 1px solid rgba(222, 214, 199, 0.82);
      vertical-align: top;
      min-width: 0;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    th { background: #faf5ea; text-align: left; font-size: 13px; color: #797260; font-weight: 760; }
    td { font-size: 13px; }
    tr:hover td { background: rgba(250, 247, 239, 0.72); }
    .risk-cell { width: 92px; }
    .score-cell { width: 150px; }
    .num-cell {
      width: 58px;
      color: var(--gold);
      font-family: ui-serif, "Songti SC", serif;
      font-size: 18px;
      font-weight: 780;
      text-align: center;
    }
    .action-cell { width: 300px; }
    .table-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .table-actions button {
      width: auto;
      height: 28px;
      padding: 0 8px;
      font-size: 12px;
      background: #fffdf7;
      color: var(--graphite);
      border-color: var(--line);
    }
    .table-actions button.active {
      background: #edf6ed;
      color: var(--accent);
      border-color: #a9c4ad;
    }
    .move-to-control {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      height: 28px;
      padding: 0 5px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fffdf7;
      color: var(--graphite);
      font-size: 12px;
      font-weight: 760;
    }
    .move-to-control input {
      width: 42px;
      height: 22px;
      padding: 0 4px;
      border: 1px solid #d9caa8;
      border-radius: 5px;
      background: #fff;
      text-align: center;
      font-size: 12px;
      font-weight: 760;
    }
    .move-to-control button {
      height: 22px;
      min-width: 26px;
      padding: 0 5px;
      border: 0;
      background: #edf6ed;
      color: var(--accent);
      box-shadow: none;
      font-size: 12px;
    }
    .sort-view-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 16px;
      border-bottom: 1px solid var(--line);
      background: #fffdf7;
    }
    .sort-view-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .sort-view-tabs button {
      width: auto;
      height: 30px;
      padding: 0 12px;
      border-color: var(--line);
      background: #fffaf0;
      color: #665b49;
      box-shadow: none;
      font-size: 12px;
    }
    .sort-view-tabs button.active {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    .official-table, .prefill-table {
      font-size: 12px;
    }
    .official-code {
      color: var(--accent);
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-weight: 800;
      letter-spacing: 0;
    }
    .prefill-note {
      color: #665b49;
      font-size: 12px;
      line-height: 1.45;
    }
    .recommendation-table th, .recommendation-table td {
      padding: 8px 10px;
    }
    .recommendation-table .school-cell {
      gap: 6px;
    }
    .recommendation-table .school-name {
      font-size: 13px;
      line-height: 1.28;
    }
    .recommendation-table .major-name,
    .recommendation-table .mini,
    .recommendation-table .identity-line {
      font-size: 11px;
      line-height: 1.35;
    }
    .compact-lines {
      display: grid;
      gap: 3px;
      line-height: 1.28;
      min-width: 0;
    }
    .compact-line {
      display: flex;
      gap: 6px;
      align-items: flex-start;
      color: #675f52;
      font-size: 11px;
      min-width: 0;
    }
    .compact-line b {
      flex: 0 0 auto;
      color: #514938;
    }
    .compact-line span {
      min-width: 0;
      white-space: normal;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    .compact-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      min-width: 0;
    }
    .compact-tag {
      display: inline-flex;
      align-items: center;
      flex: 0 0 auto;
      min-height: 20px;
      padding: 1px 6px;
      border-radius: 999px;
      background: #f6efe0;
      color: #665b49;
      font-size: 11px;
      font-weight: 760;
    }
    .compact-note {
      color: #665b49;
      font-size: 12px;
    }
    .charter-inline {
      display: grid;
      gap: 4px;
      margin-top: 5px;
      color: #675f52;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 11px;
      line-height: 1.35;
    }
    .charter-topline {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 5px;
    }
    .charter-status {
      display: inline-flex;
      align-items: center;
      min-height: 20px;
      padding: 1px 6px;
      border-radius: 999px;
      border: 1px solid #ded6c7;
      background: #fffaf0;
      color: #665b49;
      font-weight: 780;
      white-space: nowrap;
    }
    .charter-status.tooltip-trigger {
      cursor: help;
    }
    .charter-status.tooltip-trigger:focus-visible {
      outline: 2px solid rgba(31, 111, 76, .28);
      outline-offset: 2px;
    }
    .charter-status.verified {
      border-color: #bed7bf;
      background: #edf7ed;
      color: #1f6f4c;
    }
    .charter-status.pending {
      border-color: #efd39b;
      background: #fff7df;
      color: #91651f;
    }
    .charter-status.alert {
      border-color: #efc6bf;
      background: #fff4f1;
      color: var(--danger);
    }
    .charter-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .charter-rule {
      display: inline-flex;
      max-width: 100%;
      min-height: 20px;
      padding: 1px 6px;
      border-radius: 6px;
      background: #f7f0df;
      color: #5f574b;
      font-size: 11px;
      font-weight: 700;
    }
    .charter-rule b {
      color: #2f332f;
      margin-right: 3px;
      white-space: nowrap;
    }
    .charter-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 22px;
      padding: 2px 7px;
      border: 1px solid #c9bda8;
      border-radius: 6px;
      background: #fffdf7;
      color: var(--accent);
      font-size: 11px;
      font-weight: 780;
      text-decoration: none;
      white-space: nowrap;
    }
    .charter-link:hover {
      border-color: #b6a579;
      background: #f7f0df;
      color: var(--accent-dark);
      text-decoration: none;
    }
    .charter-link.disabled {
      border-color: #e1ddd3;
      background: #f5f2eb;
      color: #9b9488;
      pointer-events: none;
    }
    .compact-details summary {
      margin-top: 3px;
      color: var(--accent);
      font-size: 11px;
      font-weight: 760;
      cursor: pointer;
    }
    .compact-details ul {
      margin: 6px 0 0;
      padding-left: 16px;
    }
    .compact-details li {
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    .lock-badge {
      display: inline-flex;
      margin-top: 3px;
      padding: 1px 6px;
      border-radius: 999px;
      background: #edf6ed;
      color: var(--accent);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 11px;
      font-weight: 800;
    }
    .volunteer-toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: #fbf8f0;
    }
    .review-guide {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfa;
    }
    .review-list {
      display: grid;
      gap: 8px;
    }
    .compare-grid, .audit-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }
    .step-panel .compare-grid { margin-bottom: 14px; }
    .strategy-description-panel {
      margin: 0;
      padding: 5px 7px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf7;
      text-align: left;
    }
    .strategy-summary-note {
      margin-left: 0;
      color: #6f6657;
      font-size: 10.5px;
      font-weight: 760;
    }
    .strategy-description-panel .mini {
      margin: 4px 0 5px;
      text-align: left;
    }
    .strategy-description-panel .compare-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
      margin-bottom: 0;
      max-height: 118px;
      overflow: auto;
    }
    .compare-card, .audit-card {
      position: relative;
      border: 1px solid var(--line);
      border-radius: 9px;
      background: #fffdf7;
      padding: 8px;
      display: grid;
      gap: 6px;
      text-align: left;
    }
    .strategy-card {
      align-content: start;
      min-width: 0;
      cursor: pointer;
      transition: border-color 0.16s ease, box-shadow 0.16s ease, background 0.16s ease;
    }
    .strategy-card:hover {
      border-color: #a8c4ad;
      box-shadow: 0 8px 20px rgba(74, 91, 69, 0.08);
    }
    .strategy-card:focus-visible {
      outline: 2px solid rgba(31, 111, 76, 0.22);
      outline-offset: 2px;
    }
    .compare-card.active {
      border-color: #8db99b;
      background: #edf6ed;
      box-shadow: inset 0 0 0 1px rgba(31, 111, 76, 0.08);
    }
    .compare-card h3, .audit-card h3 { margin: 0; }
    .strategy-card-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-width: 0;
    }
    .strategy-card-head h3 {
      min-width: 0;
      color: #253028;
      font-size: 13px;
      line-height: 1.2;
      text-align: left;
    }
    .strategy-select-chip {
      flex: 0 0 auto;
      min-height: 22px;
      padding: 3px 7px;
      border: 1px solid rgba(222, 214, 199, 0.88);
      border-radius: 999px;
      background: #fffaf0;
      color: #746a5a;
      font-size: 10px;
      font-weight: 820;
      white-space: nowrap;
    }
    .strategy-card.active .strategy-select-chip {
      border-color: #8db99b;
      background: #1f6f4c;
      color: #fff;
    }
    .strategy-setting-grid {
      display: grid;
      grid-template-columns: 38px minmax(0, 1fr) minmax(58px, 0.68fr);
      overflow: hidden;
      border: 1px solid rgba(222, 214, 199, 0.82);
      border-radius: 7px;
      background: #fffef9;
    }
    .strategy-setting-cell {
      min-width: 0;
      min-height: 24px;
      display: flex;
      align-items: center;
      justify-content: flex-start;
      padding: 3px 5px;
      border-right: 1px solid rgba(222, 214, 199, 0.62);
      border-bottom: 1px solid rgba(222, 214, 199, 0.62);
      color: #625948;
      font-size: 11px;
      font-weight: 760;
      line-height: 1.2;
      text-align: left;
    }
    .strategy-setting-cell:nth-child(3n) { border-right: 0; }
    .strategy-setting-cell:nth-last-child(-n + 3) { border-bottom: 0; }
    .strategy-setting-head {
      min-height: 20px;
      background: #f7f1e5;
      color: #7b705f;
      font-size: 10px;
      font-weight: 850;
    }
    .strategy-band-label {
      color: #253028;
      font-weight: 900;
    }
    .strategy-readonly-value {
      width: 100%;
      min-width: 0;
      overflow-wrap: anywhere;
    }
    .strategy-setting-cell input {
      width: 100%;
      height: 22px;
      min-width: 0;
      padding: 0 4px;
      border-radius: 5px;
      border-color: #d7c394;
      background: #fffaf0;
      color: #253028;
      font-size: 11px;
      font-weight: 820;
      text-align: left;
    }
    .strategy-gap-number {
      display: inline-grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 3px;
      align-items: center;
      width: 100%;
      min-width: 0;
    }
    .strategy-gap-number input {
      height: 22px;
    }
    .strategy-gap-number span {
      color: #746a5a;
      font-size: 10px;
      font-weight: 760;
      white-space: nowrap;
    }
    .strategy-gap-range {
      display: inline-grid;
      grid-template-columns: auto minmax(34px, 0.72fr) auto;
      gap: 3px;
      align-items: center;
      width: 100%;
      min-width: 0;
      color: #746a5a;
      font-size: 9.5px;
      font-weight: 760;
      line-height: 1.15;
    }
    .strategy-gap-range.safe {
      grid-template-columns: minmax(34px, 0.72fr) auto;
    }
    .strategy-gap-range input {
      height: 22px;
      padding: 0 3px;
      text-align: center;
    }
    .strategy-gap-range span {
      white-space: nowrap;
    }
    .strategy-card-foot {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
    }
    .strategy-card-foot span {
      min-width: 0;
      padding: 4px 5px;
      border-radius: 6px;
      background: #f8f1e4;
      color: #5f574c;
      font-size: 11px;
      font-weight: 740;
      text-align: left;
      line-height: 1.2;
    }
    .strategy-card-foot b {
      display: block;
      color: var(--accent);
      font-size: 14px;
      line-height: 1.15;
    }
    .strategy-ratio-strip {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 4px;
    }
    .strategy-ratio-strip span {
      display: grid;
      gap: 2px;
      min-width: 0;
      padding: 5px 4px;
      border: 1px solid rgba(222, 214, 199, 0.76);
      border-radius: 7px;
      background: rgba(255, 253, 247, 0.82);
      color: #776d5d;
      font-size: 10px;
      font-weight: 760;
      text-align: center;
      line-height: 1.15;
    }
    .strategy-ratio-strip b {
      color: #253028;
      font-size: 13px;
      line-height: 1;
    }
    .custom-ratio-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 5px;
    }
    .custom-ratio-grid label {
      gap: 3px;
      color: #655b49;
      font-size: 10px;
      font-weight: 760;
      line-height: 1.15;
    }
    .custom-ratio-grid input {
      height: 28px;
      padding: 0 5px;
      text-align: center;
      font-size: 12px;
      font-weight: 820;
      background: #fffaf0;
      border-color: #d9c59a;
    }
    .compare-stats {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 7px;
    }
    .compare-stats span, .audit-card span {
      min-height: 42px;
      padding: 7px;
      border-radius: 7px;
      background: #f8f1e4;
      color: #5f574c;
      font-size: 12px;
      font-weight: 700;
    }
    .compare-stats b, .audit-card b {
      display: block;
      color: var(--accent);
      font-size: 16px;
    }
    .compare-actions {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
    }
    .compare-actions-right {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      flex: 0 0 auto;
    }
    .compare-actions-right .help-icon {
      width: 14px;
      height: 14px;
      flex-basis: 14px;
      font-size: 10px;
    }
    .compare-actions button {
      width: auto;
      min-width: 94px;
      height: 32px;
      font-size: 12px;
      padding: 0 10px;
    }
    .audit-list {
      display: grid;
      gap: 8px;
      margin-top: 12px;
    }
    .audit-row {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(0, 1.2fr) minmax(0, 1.4fr);
      gap: 10px;
      align-items: start;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf7;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
    }
    .audit-level {
      display: inline-flex;
      width: fit-content;
      align-items: center;
      min-height: 22px;
      padding: 2px 8px;
      border-radius: 999px;
      background: #f6efe0;
      color: #7a6a51;
      font-weight: 800;
    }
    .audit-level.high { background: #fff0ed; color: var(--danger); }
    .audit-level.medium { background: #fff6df; color: #9c6a14; }
    .audit-level.low { background: #edf6ed; color: var(--accent); }
    .commercial-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }
    .commercial-card {
      min-height: 118px;
      border: 1px solid var(--line);
      border-radius: 9px;
      background: #fffdf7;
      padding: 11px;
      display: grid;
      align-content: start;
      gap: 6px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
    }
    .commercial-card b {
      display: block;
      color: #242b25;
      font-size: 13px;
    }
    .status-chip, .evidence-badge {
      display: inline-flex;
      width: fit-content;
      align-items: center;
      min-height: 22px;
      padding: 2px 8px;
      border-radius: 999px;
      background: #f6efe0;
      color: #7a6a51;
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
    }
    .status-chip.ok, .evidence-badge.strong { background: #edf6ed; color: var(--accent); }
    .status-chip.warn, .evidence-badge.medium { background: #fff6df; color: #9c6a14; }
    .status-chip.danger, .evidence-badge.weak { background: #fff0ed; color: var(--danger); }
    .backtest-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }
    .backtest-card {
      border: 1px solid var(--line);
      border-radius: 9px;
      background: #fbf8f0;
      padding: 11px;
      font-size: 12px;
    }
    .backtest-card b {
      display: block;
      color: var(--accent);
      font-size: 18px;
    }
    .edge-warnings {
      display: grid;
      gap: 8px;
      margin-top: 12px;
    }
    .edge-warning {
      padding: 9px 10px;
      border: 1px solid #e6ceb0;
      border-radius: 8px;
      background: #fff8eb;
      color: #6d4a1d;
      font-size: 12px;
      font-weight: 700;
    }
    .identity-line, .knowledge-line {
      margin-top: 4px;
      color: #746b5d;
      font-size: 12px;
    }
    .knowledge-line b { color: var(--accent); }
    .review-check {
      display: flex;
      grid-template-columns: none;
      align-items: flex-start;
      gap: 8px;
      color: var(--ink);
      font-size: 13px;
    }
    .review-check input {
      width: 16px;
      height: 16px;
      margin-top: 2px;
      flex: 0 0 auto;
    }
    .pill {
      display: inline-flex;
      min-height: 24px;
      align-items: center;
      padding: 2px 10px;
      border-radius: 7px;
      color: #fff;
      font-size: 12px;
      font-weight: 760;
      white-space: nowrap;
    }
    details { margin-top: 8px; }
    summary { cursor: pointer; color: var(--accent); font-weight: 760; }
    ul { margin: 8px 0 0; padding-left: 18px; }
    li { margin: 4px 0; }
    .step-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      background: #fbf8f0;
    }
    .step-title h2 {
      margin: 0;
      font-size: 17px;
      line-height: 1.2;
    }
    .step-title span {
      color: var(--muted);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 13px;
    }
    .step-tabs {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 0;
      margin-bottom: 14px;
      padding: 0;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(255, 255, 252, 0.92);
      box-shadow: var(--shadow-soft);
      overflow: hidden;
    }
    .step-tab {
      min-height: 64px;
      padding: 8px 12px;
      border: 0;
      border-right: 1px solid var(--line);
      border-radius: 0;
      background: transparent;
      color: #857c6b;
      font-size: 15px;
      font-weight: 760;
      line-height: 1.2;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      box-shadow: none;
    }
    .step-tab span {
      display: block;
      margin-top: 3px;
      font-size: 11px;
      font-weight: 600;
      opacity: 0.72;
    }
    .step-tab:last-child { border-right: 0; }
    .step-tab:hover {
      background: #faf5ea;
      color: var(--graphite);
    }
    .step-tab.active {
      background: linear-gradient(180deg, #2b7656 0%, #155238 100%);
      color: #fff;
      box-shadow: inset 0 -3px 0 var(--gold);
    }
    .step-panel[hidden] { display: none; }
    .checklist {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .check {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 13px 14px;
      background: #fbf8f0;
    }
    .loading { opacity: 0.7; pointer-events: none; }
    .progress-backdrop {
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      background: rgba(38, 33, 25, 0.34);
      backdrop-filter: blur(4px);
      z-index: 30;
    }
    .progress-backdrop.open { display: flex; }
    .progress-card {
      width: min(420px, calc(100vw - 36px));
      padding: 20px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fffef9;
      box-shadow: 0 24px 90px rgba(42, 34, 22, 0.25);
    }
    .progress-card h2 { margin-bottom: 6px; }
    .progress-track {
      height: 12px;
      margin-top: 14px;
      overflow: hidden;
      border-radius: 999px;
      background: #e8dfcf;
    }
    .progress-fill {
      width: 0;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), var(--gold));
      transition: width 180ms ease;
    }
    .progress-meta {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
    }
    .footer {
      margin: 20px 0 4px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 13px;
      text-align: center;
    }
    .control-value {
      min-height: 36px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .controls > label:first-child input.rank-input,
    .controls .rank-input {
      width: 100%;
      min-width: 0;
      box-sizing: border-box;
      height: 36px;
      padding: 0 7px;
      border: 2px solid #1f6f4c;
      border-radius: 8px;
      background: #fffefa;
      box-shadow: inset 0 0 0 1px rgba(244, 211, 123, 0.72), 0 0 0 2px rgba(31, 111, 76, 0.08);
      color: #173f2c;
      font-family: "Bahnschrift", "DIN Alternate", "Arial Narrow", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 25px;
      font-weight: 850;
      line-height: 1;
      letter-spacing: 0;
    }
    .controls > label:first-child input.rank-input::placeholder,
    .controls .rank-input::placeholder {
      font-size: 11px !important;
      line-height: 36px;
      color: #746a5a;
      opacity: 1;
    }
    .generate-wrap {
      display: grid;
      gap: 5px;
      align-self: end;
      min-width: 0;
      justify-self: stretch;
      width: 100%;
      padding-left: 10px;
      transform: none;
    }
    .generate-actions {
      display: grid;
      grid-template-columns: minmax(104px, 1.15fr) minmax(82px, 0.9fr) minmax(82px, 0.9fr);
      gap: 6px;
      align-items: center;
    }
    .generate-actions button {
      width: 100%;
      min-width: 0;
      height: 36px;
      padding: 0 6px;
      border-radius: 7px;
      font-size: 12px;
      white-space: nowrap;
    }
    .generate-actions button[type="submit"] {
      border-color: #174f36;
      background: linear-gradient(180deg, #196a49 0%, #0f4b32 100%);
      box-shadow: 0 8px 16px rgba(31, 111, 76, 0.16);
      font-weight: 850;
    }
    .generate-actions button.secondary-report-button {
      background: #fffdf7;
      border-color: #cfc2a8;
      color: #4f594e;
      box-shadow: none;
      font-size: 11px;
      font-weight: 760;
    }
    .generate-actions button.secondary-report-button:hover {
      background: #edf6ed;
      border-color: #a9c6ad;
      color: var(--accent);
    }
    .generate-note {
      position: absolute;
      top: 6px;
      left: 12px;
      right: auto;
      min-height: 0;
      max-width: calc(100% - 24px);
      padding: 2px 8px;
      border: 1px solid #efc6bf;
      border-radius: 999px;
      background: #fff3ef;
      color: var(--danger);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 10px;
      font-weight: 760;
      text-align: left;
      line-height: 1.35;
      overflow-wrap: anywhere;
      pointer-events: none;
      z-index: 3;
    }
    .generate-note:empty { display: none; }
    .settings-trigger-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
      min-width: 0;
    }
    .settings-trigger-row button {
      min-width: 0;
      min-height: 28px;
      height: auto;
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      align-items: center;
      gap: 6px;
      padding: 4px 7px;
      border-color: #cfc2a8;
      background: #fffdf7;
      color: var(--accent);
      box-shadow: none;
      text-align: left;
    }
    .settings-trigger-row button:hover {
      background: #edf6ed;
      border-color: #a9c6ad;
    }
    .settings-trigger-title {
      font-size: 11px;
      font-weight: 860;
      white-space: nowrap;
    }
    .settings-trigger-note {
      min-width: 0;
      overflow: hidden;
      color: #72706a;
      font-size: 10px;
      font-weight: 680;
      line-height: 1.2;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .settings-slide-backdrop {
      position: fixed;
      inset: 0;
      display: none;
      background: rgba(37, 32, 24, 0.24);
      z-index: 92;
    }
    .settings-slide-backdrop.open { display: block; }
    .settings-slide-panel {
      position: fixed;
      top: 0;
      right: 0;
      z-index: 93;
      width: min(620px, 68vw);
      max-width: 92vw;
      height: 100vh;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      border-left: 1px solid var(--line);
      background: #fffef9;
      box-shadow: -22px 0 64px rgba(42, 34, 22, 0.22);
      pointer-events: none;
      transform: translateX(104%);
      transition: transform 0.2s ease;
      visibility: hidden;
    }
    .settings-slide-panel.open {
      pointer-events: auto;
      transform: translateX(0);
      visibility: visible;
    }
    .settings-slide-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
      padding: 16px 18px 12px;
      border-bottom: 1px solid rgba(222, 214, 199, 0.82);
      background: #fbf8f0;
      text-align: left;
    }
    .settings-slide-head h2 {
      margin: 0;
      color: #223026;
      font-size: 18px;
      line-height: 1.2;
    }
    .settings-slide-head .mini {
      margin-top: 4px;
      color: #70675a;
      font-size: 11px;
    }
    .settings-slide-head button {
      width: auto;
      min-width: 64px;
      height: 30px;
      padding: 0 10px;
      background: #fffdf7;
      border-color: #cfc2a8;
      color: #4f594e;
      box-shadow: none;
      font-size: 12px;
    }
    .settings-slide-body {
      min-height: 0;
      overflow: auto;
      padding: 14px 16px 18px;
      background: #fffef9;
    }
    .settings-slide-content[hidden] { display: none; }
    .settings-slide-content.strategy-description-panel,
    .settings-slide-content.profile-panel {
      max-height: none;
      overflow: visible;
      padding: 10px;
    }
    .settings-slide-content .compare-grid {
      max-height: none;
      overflow: visible;
    }
    .field-hint {
      color: #958b79;
      font-size: 10px;
      font-weight: 600;
    }
    .control-select {
      height: 32px;
      padding: 0 7px;
      background: #fffdf7;
      font-size: 11px;
    }
    .step-tabs {
      align-items: stretch;
      padding: 0;
    }
    .step-tab {
      position: relative;
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      align-content: center;
      column-gap: 10px;
      min-height: 66px;
      text-align: left;
      white-space: normal;
    }
    .step-index {
      color: inherit;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 30px;
      font-style: italic;
      line-height: 1;
    }
    .step-tab strong {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 15px;
      font-weight: 800;
    }
    .step-tab span {
      margin-top: 2px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .step-tab.active::after {
      content: "";
      position: absolute;
      right: -12px;
      top: 0;
      width: 24px;
      height: 100%;
      background: inherit;
      transform: skewX(-16deg);
      border-right: 1px solid #0d4b35;
      z-index: 1;
    }
    .step-tab > * { position: relative; z-index: 2; }
    .data-line {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
      color: var(--muted);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
    }
    .table-wrap {
      overflow: auto;
      border: 1px solid rgba(222, 214, 199, 0.78);
      border-radius: 9px;
      background: #fffef9;
    }
    .table-wrap table { min-width: 760px; }
    .matched-university-wrap {
      --matched-header-bg: #f7f1e5;
      max-height: min(1480px, max(1320px, 96vh));
      overflow: auto;
      scrollbar-gutter: auto;
    }
    .matched-university-wrap table.matched-table {
      width: 100%;
      min-width: 1120px;
      table-layout: fixed;
      border-collapse: separate;
      border-spacing: 0;
    }
    .matched-table th,
    .matched-table td {
      padding: 12px 10px;
      line-height: 1.42;
      word-break: break-word;
    }
    .matched-table th {
      position: sticky;
      top: 0;
      z-index: 2;
      border-bottom: 1px solid #d8ccb6;
      background: var(--matched-header-bg);
      color: #695f4f;
      font-size: 12px;
      letter-spacing: 0;
    }
    .matched-table tbody tr:nth-child(even) td { background: #fffbf2; }
    .matched-table tbody tr:hover td { background: #f4f8ef; }
    .matched-table tbody td {
      border-bottom-color: rgba(222, 214, 199, 0.58);
    }
    .matched-table th:nth-child(1), .matched-table td:nth-child(1) { width: 21.2%; }
    .matched-table th:nth-child(2), .matched-table td:nth-child(2) { width: 7%; }
    .matched-table th:nth-child(3), .matched-table td:nth-child(3) { width: 12%; }
    .matched-table th:nth-child(4), .matched-table td:nth-child(4) { width: 6%; }
    .matched-table th:nth-child(5), .matched-table td:nth-child(5) { width: 9%; }
    .matched-table th:nth-child(6), .matched-table td:nth-child(6) { width: 15%; }
    .matched-table th:nth-child(7), .matched-table td:nth-child(7) { width: 10%; }
    .matched-table th:nth-child(8), .matched-table td:nth-child(8) { width: 7%; }
    .matched-table th:nth-child(9), .matched-table td:nth-child(9) { width: 12.8%; }
    .matched-table th:nth-child(9),
    .matched-table td:nth-child(9) {
      position: sticky;
      right: 0;
      z-index: 3;
    }
    .matched-table th:nth-child(9) {
      z-index: 5;
      background: var(--matched-header-bg);
    }
    .matched-table tbody td:nth-child(9) {
      background: #fffef9;
    }
    .matched-table tbody tr:nth-child(even) td:nth-child(9) {
      background: #fffbf2;
    }
    .matched-table tbody tr:hover td:nth-child(9) {
      background: #f4f8ef;
    }
    .matched-table .school-cell {
      min-width: 0;
    }
    .matched-table .school-name {
      font-size: 14px;
      line-height: 1.32;
    }
    .matched-table .major-name,
    .matched-table .identity-line {
      line-height: 1.45;
    }
    .matched-table th:nth-child(8),
    .matched-table td:nth-child(8) {
      white-space: nowrap;
      word-break: keep-all;
      overflow-wrap: normal;
    }
    .matched-table th:nth-child(2),
    .matched-table th:nth-child(3),
    .matched-table th:nth-child(4),
    .matched-table th:nth-child(5),
    .matched-table td:nth-child(2),
    .matched-table td:nth-child(3),
    .matched-table td:nth-child(4),
    .matched-table td:nth-child(5) {
      white-space: normal;
      word-break: break-word;
      overflow-wrap: anywhere;
    }
    .matched-table th:nth-child(2),
    .matched-table th:nth-child(3),
    .matched-table th:nth-child(4),
    .matched-table th:nth-child(5),
    .matched-table th:nth-child(8),
    .matched-table td:nth-child(2),
    .matched-table td:nth-child(3),
    .matched-table td:nth-child(4),
    .matched-table td:nth-child(5),
    .matched-table td:nth-child(8),
    .matched-table td:nth-child(9) {
      text-align: center;
    }
    .matched-table td:nth-child(4) {
      color: #5f5a4e;
      font-size: 11px;
      font-weight: 700;
    }
    .matched-table .match-meter {
      grid-template-columns: minmax(0, 1fr);
      gap: 5px;
    }
    .matched-table .match-meter b {
      display: block;
      font-size: 12px;
    }
    .matched-table .success-rate-text {
      font-weight: 880;
    }
    .plan-2026-cell {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 22px;
      padding: 2px 7px;
      border-radius: 6px;
      border: 1px solid #d6c7ad;
      background: #fffaf0;
      color: #574b3a;
      font-size: 11px;
      font-weight: 820;
      line-height: 1.2;
      white-space: nowrap;
    }
    .plan-2026-cell.estimate {
      border-color: #e3c17a;
      background: #fff7df;
      color: #7a5514;
    }
    .plan-2026-cell.missing {
      border-style: dashed;
      color: #897b66;
    }
    .admission-history {
      display: grid;
      gap: 3px;
      min-width: 0;
      color: #4c463b;
      font-size: 11px;
      line-height: 1.35;
    }
    .admission-history-line {
      white-space: nowrap;
      word-break: keep-all;
      overflow-wrap: normal;
    }
    .admission-history-line b {
      font-weight: 780;
      color: #29241d;
    }
    .discipline-assessment-cell {
      display: grid;
      justify-items: center;
      gap: 5px;
      min-width: 0;
      color: #4d473d;
      font-size: 10px;
      line-height: 1.25;
    }
    .assessment-grade-line,
    .recommend-rate-line {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      max-width: 100%;
      white-space: nowrap;
    }
    .assessment-grade-line span,
    .recommend-rate-line span {
      color: #877d6d;
      font-weight: 720;
    }
    .assessment-grade-line b,
    .recommend-rate-line b {
      min-width: 36px;
      padding: 2px 6px;
      border-radius: 999px;
      border: 1px solid #d5c5a8;
      background: #fffaf0;
      color: #2f342b;
      font-size: 11px;
      font-weight: 860;
      line-height: 1.1;
      text-align: center;
    }
    .recommend-rate-line b {
      color: #1f6248;
      border-color: #b8d0be;
      background: #f0f8ef;
    }
    .assessment-grade-line b.missing,
    .recommend-rate-line b.missing {
      color: #897b66;
      border-style: dashed;
      background: #fffdf7;
    }
    .match-column {
      display: grid;
      gap: 7px;
      min-width: 0;
    }
    .match-column .charter-inline {
      margin-top: 0;
      gap: 3px;
      font-size: 10px;
    }
    .match-column .charter-status,
    .match-cell .charter-status {
      min-height: 18px;
      padding: 1px 5px;
      font-size: 10px;
    }
    .match-column .charter-rule,
    .match-cell .charter-rule {
      min-height: 18px;
      padding: 1px 5px;
      font-size: 10px;
    }
    .matched-table button.secondary-button {
      width: 100%;
      min-width: 0;
      height: auto;
      min-height: 30px;
      padding: 5px 7px;
      overflow-wrap: anywhere;
      white-space: normal;
      line-height: 1.25;
    }
    .matched-table button.is-selected {
      border-color: #9fc0a9;
      background: #edf6ed;
      color: var(--accent);
    }
    .matched-table .help-icon {
      width: 14px;
      height: 14px;
      flex-basis: 14px;
      font-size: 10px;
    }
    .candidate-actions {
      display: grid;
      gap: 6px;
      min-width: 0;
    }
    .candidate-actions .charter-link {
      width: 100%;
      min-height: 28px;
      font-size: 12px;
    }
    .candidate-actions button.secondary-button {
      font-size: 11px;
    }
    .sparkline {
      width: 118px;
      height: 34px;
      display: block;
    }
    .sparkline polyline {
      fill: none;
      stroke: #c6aa62;
      stroke-width: 2.2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .sparkline circle { fill: #1f6f4c; }
    .filter-pills {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .title-filter-pills {
      justify-content: flex-end;
      max-width: 70%;
      gap: 6px;
    }
    .title-filter-pills .filter-pill {
      min-height: 22px;
      padding: 1px 8px;
      font-size: 10.5px;
    }
    .filter-pill {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 3px 11px;
      border: 1px solid #e5d8bf;
      border-radius: 999px;
      background: #fffaf0;
      color: #7c705c;
      font-size: 12px;
      font-weight: 760;
    }
    button.filter-pill {
      width: auto;
      height: 30px;
      box-shadow: none;
      cursor: pointer;
    }
    .filter-pill.active {
      background: linear-gradient(180deg, #2b7656 0%, #155238 100%);
      border-color: #155238;
      color: #fff;
    }
    .match-toolbar {
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto auto auto;
      gap: 12px;
      align-items: center;
      margin: -4px 0 6px;
    }
    .match-toolbar > input {
      height: 42px;
      background: #fffdf7;
    }
    .match-toolbar > button,
    .match-toolbar .free-select-field,
    .match-toolbar .free-select-toggle {
      height: 42px;
    }
    .free-select-field {
      position: relative;
      display: inline-flex;
      min-width: 0;
    }
    .free-select-toggle {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 34px;
      padding: 0 24px 0 9px;
      border: 1px solid rgba(222, 214, 199, 0.82);
      border-radius: 7px;
      background: #fffaf0;
      color: #514b40;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }
    .free-select-help {
      position: absolute;
      top: -7px;
      right: -7px;
      z-index: 4;
      width: 17px;
      height: 17px;
      flex-basis: 17px;
      background: #f3f8f1;
      box-shadow: 0 2px 8px rgba(31, 111, 76, 0.12);
    }
    .free-select-toggle input {
      width: 15px;
      height: 15px;
      accent-color: var(--accent);
    }
    .school-cell {
      display: grid;
      gap: 6px;
      min-width: 220px;
      max-width: 100%;
      line-height: 1.38;
    }
    .option-primary {
      display: grid;
      gap: 3px;
      min-width: 0;
    }
    .school-name-line {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 5px;
      min-width: 0;
    }
    .school-name {
      font-weight: 790;
      color: #253028;
      line-height: 1.35;
      white-space: normal;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    .option-code {
      display: inline-flex;
      align-items: center;
      min-height: 18px;
      padding: 1px 5px;
      border: 1px solid #d8ccb6;
      border-radius: 5px;
      background: #fffaf0;
      color: #6f624d;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 10px;
      font-weight: 800;
      line-height: 1;
      white-space: nowrap;
    }
    .major-name {
      margin-top: 2px;
      color: #4d4639;
      font-size: 12px;
      line-height: 1.45;
      font-weight: 760;
      white-space: normal;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    .option-meta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      min-width: 0;
    }
    .option-tag-row {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      min-width: 0;
      padding-top: 1px;
    }
    .option-meta-chip {
      display: inline-flex;
      align-items: center;
      max-width: 100%;
      min-height: 19px;
      padding: 1px 6px;
      border-radius: 999px;
      border: 1px solid #e1d7c5;
      background: #fffdf7;
      color: #6d6252;
      font-size: 11px;
      font-weight: 740;
      line-height: 1.2;
      white-space: nowrap;
    }
    .option-meta-chip.important {
      border-color: #c8d9c9;
      background: #f3f8f1;
      color: var(--accent);
    }
    .option-project-tag {
      display: inline-flex;
      align-items: center;
      max-width: 100%;
      min-height: 18px;
      padding: 1px 6px;
      border-radius: 999px;
      border: 1px solid #d8ccb6;
      background: #f8f1e2;
      color: #6a5c46;
      font-size: 10px;
      font-weight: 780;
      line-height: 1.2;
      white-space: nowrap;
    }
    .school-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: 1px;
    }
    .level-tags {
      justify-content: center;
      margin-top: 0;
    }
    .school-tag {
      display: inline-flex;
      min-height: 19px;
      align-items: center;
      padding: 1px 6px;
      border-radius: 999px;
      background: #f6efe0;
      color: #73664f;
      font-size: 11px;
      font-weight: 750;
    }
    .school-tag.elite {
      background: #edf6ed;
      color: var(--accent);
      border: 1px solid #c8d9c9;
    }
    .match-meter {
      display: grid;
      grid-template-columns: 72px auto;
      align-items: center;
      gap: 8px;
    }
    .match-meter .track { height: 7px; }
    .matched-table .school-cell > div { min-width: 0; }
    .matched-table .calc-value,
    .recommendation-table .calc-value {
      white-space: normal;
    }
    .matched-table .match-meter {
      grid-template-columns: minmax(0, 1fr);
      gap: 5px;
    }
    .matched-table .match-meter b {
      display: block;
      font-size: 12px;
    }
    .calc-value {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      max-width: 100%;
      vertical-align: middle;
      white-space: nowrap;
    }
    .calc-value.block {
      display: flex;
      justify-content: center;
    }
    .help-icon {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 16px;
      height: 16px;
      flex: 0 0 16px;
      border-radius: 999px;
      border: 1px solid #c8d9c9;
      background: #f3f8f1;
      color: var(--accent);
      font-size: 11px;
      font-weight: 900;
      line-height: 1;
      cursor: help;
    }
    .tooltip-layer {
      position: fixed;
      left: 0;
      top: 0;
      z-index: 9999;
      width: max-content;
      max-width: min(340px, calc(100vw - 24px));
      padding: 8px 10px;
      border: 1px solid #cad8c7;
      border-radius: 8px;
      background: #1f2b24;
      color: #fff;
      box-shadow: 0 10px 22px rgba(32, 42, 34, .18);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
      font-weight: 650;
      line-height: 1.45;
      white-space: pre-line;
      text-align: left;
      opacity: 0;
      visibility: hidden;
      pointer-events: none;
      transform: translateY(4px);
      transition: opacity .12s ease, transform .12s ease, visibility .12s ease;
    }
    .tooltip-layer.open {
      opacity: 1;
      visibility: visible;
      transform: translateY(0);
    }
    .score-band-wrap {
      overflow: visible;
    }
    .score-band-title {
      margin: 16px 0 10px;
    }
    .score-band-wrap table {
      min-width: 0;
    }
    .risk-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 48px;
      min-height: 26px;
      padding: 2px 9px;
      border-radius: 7px;
      color: #fff;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }
    .rail-section {
      padding: 0 0 16px;
      margin-bottom: 16px;
      border-bottom: 1px solid rgba(222, 214, 199, 0.82);
    }
    .rail-section:last-child { margin-bottom: 0; border-bottom: 0; padding-bottom: 0; }
    .donut-wrap {
      display: grid;
      grid-template-columns: 128px minmax(0, 1fr);
      gap: 12px;
      align-items: center;
      margin: 10px 0 12px;
    }
    .donut {
      width: 118px;
      height: 118px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: conic-gradient(var(--danger) 0deg, var(--danger) 120deg, var(--steady) 120deg, var(--steady) 250deg, var(--safe) 250deg, var(--safe) 360deg);
      box-shadow: inset 0 0 0 1px rgba(120, 95, 55, 0.12);
    }
    .donut-center {
      width: 72px;
      height: 72px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: #fffef9;
      color: #242b25;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 26px;
      font-weight: 800;
      box-shadow: 0 0 0 1px rgba(222, 214, 199, 0.88);
    }
    .risk-legend {
      display: grid;
      gap: 8px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
    }
    .legend-row {
      display: grid;
      grid-template-columns: 12px 1fr auto;
      gap: 8px;
      align-items: center;
    }
    .dot { width: 9px; height: 9px; border-radius: 50%; }
    .rail-stat {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 10px;
    }
    .rail-card {
      min-height: 70px;
      padding: 11px 12px;
      border: 1px solid var(--line);
      border-radius: 9px;
      background: #fbf8f0;
    }
    .rail-card b {
      display: block;
      color: var(--accent);
      font-family: Georgia, "Times New Roman", serif;
      font-size: 20px;
      line-height: 1.15;
    }
    .summary-good {
      margin-top: 10px;
      padding: 9px 10px;
      border-radius: 8px;
      background: #edf6ed;
      color: var(--accent-dark);
      font-size: 12px;
      font-weight: 760;
    }
    .risk-list {
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .risk-list li {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      margin: 0;
      padding: 8px 10px;
      border-radius: 8px;
      background: #fff8f4;
      color: #6f4b38;
      font-size: 12px;
    }
    .risk-list .count {
      min-width: 26px;
      padding: 1px 7px;
      border-radius: 999px;
      background: #f2c6c2;
      color: #a33838;
      text-align: center;
      font-weight: 800;
    }
    .cart-summary-panel {
      padding-bottom: 0;
      margin-bottom: 0;
      border-bottom: 0;
    }
    .cart-summary-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: start;
    }
    .cart-summary-head h2 {
      margin-bottom: 5px;
      font-size: 18px;
    }
    .cart-total-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 28px;
      padding: 3px 10px;
      border: 1px solid #bfd2c3;
      border-radius: 999px;
      background: #edf6ed;
      color: var(--accent);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }
    .cart-count-grid,
    .drawer-count-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 14px;
    }
    .cart-count,
    .drawer-count {
      min-width: 0;
      min-height: 68px;
      padding: 10px 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf7;
      color: var(--ink);
      box-shadow: none;
      text-align: left;
    }
    .cart-count:hover {
      background: #f7f0df;
      border-color: #c8b991;
      color: var(--ink);
    }
    .cart-count b,
    .drawer-count b {
      display: block;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 25px;
      line-height: 1;
    }
    .cart-count span,
    .drawer-count span {
      display: block;
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }
    .cart-count.challenge b,
    .drawer-count.challenge b { color: var(--danger); }
    .cart-count.steady b,
    .drawer-count.steady b { color: var(--steady); }
    .cart-count.safe b,
    .drawer-count.safe b { color: var(--safe); }
    .cart-stack {
      display: flex;
      height: 10px;
      margin-top: 11px;
      border-radius: 999px;
      overflow: hidden;
      background: #e5dfd3;
    }
    .cart-stack span {
      display: block;
      min-width: 0;
      height: 100%;
    }
    .cart-stack .challenge { background: var(--danger); }
    .cart-stack .steady { background: var(--steady); }
    .cart-stack .safe { background: var(--safe); }
    .cart-stack .unknown { background: #8a877e; }
    .cart-alert-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }
    .cart-alert-row span {
      min-width: 0;
      padding: 6px 8px;
      border: 1px solid #ecd7ba;
      border-radius: 8px;
      background: #fff8ed;
      color: #775437;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
      font-weight: 800;
      text-align: center;
      white-space: nowrap;
    }
    .cart-preview-list {
      display: grid;
      gap: 8px;
      margin-top: 13px;
      max-height: 260px;
      overflow: auto;
      padding-right: 2px;
    }
    .cart-preview-item,
    .drawer-item {
      display: grid;
      gap: 10px;
      align-items: start;
      border: 1px solid rgba(222, 214, 199, 0.82);
      border-radius: 8px;
      background: #fffdf7;
      padding: 9px 10px;
    }
    .drawer-item {
      grid-template-columns: 30px minmax(170px, 1.45fr) minmax(76px, .52fr) minmax(82px, .52fr) minmax(118px, .72fr) 54px minmax(142px, .76fr);
      gap: 8px;
      min-width: 720px;
    }
    .cart-preview-item {
      grid-template-columns: minmax(0, 1fr) auto;
    }
    .drawer-order-index {
      min-width: 28px;
      height: 28px;
      display: inline-grid;
      place-items: center;
      border-radius: 999px;
      background: #edf6ed;
      color: var(--accent);
      font-size: 12px;
      font-weight: 900;
    }
    .cart-preview-item b,
    .drawer-item b {
      display: block;
      color: #253129;
      font-size: 13px;
      line-height: 1.32;
      overflow-wrap: anywhere;
    }
    .cart-preview-item .mini,
    .drawer-item .mini {
      display: block;
      margin-top: 3px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .cart-empty,
    .drawer-empty {
      padding: 14px 12px;
      border: 1px dashed #d6c8ad;
      border-radius: 8px;
      background: #fffaf0;
      color: var(--muted);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
      font-weight: 700;
      text-align: center;
    }
    .cart-actions,
    .selection-drawer-footer {
      display: grid;
      gap: 8px;
      margin-top: 14px;
    }
    .cart-actions {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .selection-drawer-footer {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .cart-actions button,
    .selection-drawer-footer button {
      min-width: 0;
      height: 34px;
      padding: 0 10px;
      font-size: 12px;
      white-space: nowrap;
    }
    .cart-actions .danger-text-button,
    .selection-drawer-footer .danger-text-button {
      padding: 0 9px;
    }
    .selection-drawer-backdrop {
      position: fixed;
      inset: 0;
      display: none;
      background: rgba(37, 32, 24, 0.26);
      z-index: 88;
    }
    .selection-drawer-backdrop.open { display: block; }
    .selection-drawer {
      position: fixed;
      top: 0;
      right: 0;
      z-index: 90;
      width: min(var(--selection-drawer-width, 840px), 70vw);
      min-width: 30vw;
      max-width: 70vw;
      height: 100vh;
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr) auto;
      gap: 0;
      border-left: 1px solid var(--line);
      background: #fffef9;
      box-shadow: -24px 0 70px rgba(42, 34, 22, 0.22);
      transform: translateX(104%);
      transition: transform .18s ease;
    }
    .selection-drawer.open { transform: translateX(0); }
    .selection-drawer-resize {
      position: absolute;
      left: -6px;
      top: 0;
      bottom: 0;
      width: 12px;
      cursor: ew-resize;
      touch-action: none;
      z-index: 2;
    }
    .selection-drawer-resize::before {
      content: "";
      position: absolute;
      left: 5px;
      top: 16px;
      bottom: 16px;
      width: 2px;
      border-radius: 999px;
      background: rgba(31, 111, 76, 0.22);
      opacity: 0;
      transition: opacity 0.16s ease;
    }
    .selection-drawer-resize:hover::before,
    .selection-drawer.resizing .selection-drawer-resize::before {
      opacity: 1;
    }
    .selection-drawer-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      padding: 18px 18px 12px;
      border-bottom: 1px solid rgba(222, 214, 199, 0.82);
    }
    .selection-drawer-head-actions {
      display: flex;
      gap: 8px;
      align-items: center;
      flex: 0 0 auto;
    }
    .selection-drawer-head h2 {
      margin-bottom: 5px;
      font-size: 19px;
    }
    .selection-drawer-head button {
      height: 32px;
      min-width: 64px;
      padding: 0 11px;
      font-size: 12px;
    }
    .cart-dock-button {
      position: fixed;
      right: 18px;
      bottom: 92px;
      z-index: 76;
      width: auto;
      min-width: 118px;
      height: 42px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 0 13px;
      border-radius: 999px;
      border-color: #174f36;
      background: linear-gradient(180deg, #196a49, #0f4b32);
      box-shadow: 0 12px 28px rgba(31, 111, 76, 0.24);
      font-size: 13px;
      white-space: nowrap;
    }
    .cart-dock-button b {
      min-width: 24px;
      height: 24px;
      display: inline-grid;
      place-items: center;
      border-radius: 999px;
      background: #fffdf7;
      color: var(--accent);
      font-size: 12px;
      font-weight: 850;
    }
    .cart-dock-button.has-items b {
      color: var(--danger);
    }
    .cart-dock-button.hidden {
      display: none;
    }
    .selection-drawer .drawer-count-grid {
      margin: 0;
      padding: 8px 18px;
      border-bottom: 1px solid rgba(222, 214, 199, 0.66);
    }
    .drawer-count {
      min-height: 36px;
      background: #fbf8f0;
    }
    .selection-drawer .drawer-count {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      min-height: 36px;
      padding: 6px 10px;
      text-align: center;
    }
    .selection-drawer .drawer-count b {
      display: inline;
      font-size: 21px;
      line-height: 1;
    }
    .selection-drawer .drawer-count span {
      display: inline;
      margin-top: 0;
      font-size: 12px;
      line-height: 1;
    }
    .selection-drawer-body {
      min-height: 0;
      overflow: auto;
      padding: 14px 18px 16px;
      background: #fbf8f0;
    }
    .drawer-group {
      margin-bottom: 14px;
    }
    .drawer-group:last-child { margin-bottom: 0; }
    .drawer-group-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
      color: #363b34;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 13px;
      font-weight: 850;
    }
    .drawer-group-head span {
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }
    .drawer-list {
      display: grid;
      gap: 8px;
    }
    .drawer-item-main {
      min-width: 0;
    }
    .drawer-info-cell {
      min-width: 0;
      display: grid;
      align-content: start;
      gap: 5px;
    }
    .drawer-info-label {
      color: #7c705c;
      font-size: 10px;
      line-height: 1;
      font-weight: 850;
      white-space: nowrap;
    }
    .drawer-info-value {
      min-width: 0;
      color: #38372f;
      font-size: 11px;
      line-height: 1.3;
    }
    .drawer-info-value .school-tags {
      gap: 4px;
    }
    .drawer-info-value .school-tag {
      height: 20px;
      padding: 0 6px;
      font-size: 10px;
    }
    .drawer-info-value .plan-2026-cell {
      min-height: 20px;
      padding: 2px 6px;
      font-size: 10px;
    }
    .drawer-info-value .discipline-assessment-cell {
      justify-items: start;
      gap: 4px;
    }
    .drawer-info-value .assessment-grade-line,
    .drawer-info-value .recommend-rate-line {
      justify-content: flex-start;
      gap: 3px;
    }
    .drawer-info-value .assessment-grade-line b,
    .drawer-info-value .recommend-rate-line b {
      min-width: 32px;
      padding: 2px 5px;
      font-size: 10px;
    }
    .drawer-item-risk {
      min-width: 0;
      display: grid;
      justify-items: center;
      align-content: start;
      gap: 5px;
    }
    .drawer-risk-title {
      color: #7c705c;
      font-size: 10px;
      line-height: 1;
      font-weight: 850;
      white-space: nowrap;
    }
    .drawer-item-tools {
      display: grid;
      justify-items: stretch;
      align-content: start;
      gap: 6px;
      min-width: 154px;
    }
    .drawer-move-row {
      display: grid;
      grid-template-columns: 26px 26px minmax(90px, 1fr);
      gap: 5px;
      align-items: center;
    }
    .drawer-move-row > button,
    .drawer-move-control button {
      width: 26px;
      min-width: 0;
      height: 24px;
      padding: 0;
      border-color: #c9bda8;
      background: #fffdf7;
      color: #4f594e;
      font-size: 14px;
      line-height: 1;
    }
    .drawer-move-row > button:disabled {
      opacity: 0.42;
      cursor: not-allowed;
    }
    .drawer-move-control {
      display: grid;
      grid-template-columns: 42px 26px;
      gap: 5px;
      align-items: center;
    }
    .drawer-move-control input {
      width: 42px;
      height: 24px;
      padding: 0 4px;
      border-radius: 5px;
      font-size: 11px;
      text-align: center;
    }
    .drawer-risk-pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 42px;
      height: 22px;
      padding: 0 7px;
      border-radius: 999px;
      color: #fff;
      font-size: 11px;
      font-weight: 850;
      white-space: nowrap;
    }
    .drawer-remove {
      width: 100%;
      min-width: 42px;
      height: 26px;
      padding: 0 8px;
      border-color: #efc6bf;
      background: #fff3ef;
      color: var(--danger);
      font-size: 11px;
    }
    .drawer-remove:hover {
      background: #ffe9e2;
      color: var(--danger);
    }
    .selection-drawer-footer {
      margin: 0;
      padding: 12px 18px 16px;
      border-top: 1px solid rgba(222, 214, 199, 0.82);
      background: #fffef9;
    }
    .sort-workbench {
      display: grid;
      gap: 12px;
      padding: 14px;
      background: #fbf8f0;
    }
    .sort-smart-strip {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .sort-smart-card {
      min-height: 66px;
      padding: 10px 12px;
      border: 1px solid rgba(222, 214, 199, 0.82);
      border-radius: 8px;
      background: #fffdf7;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }
    .sort-smart-card b {
      display: block;
      color: var(--accent);
      font-size: 20px;
      line-height: 1.1;
    }
    .sort-smart-card span {
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }
    .sort-board {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      align-items: start;
    }
    .sort-lane {
      min-width: 0;
      min-height: 180px;
      border: 1px solid rgba(222, 214, 199, 0.92);
      border-radius: 9px;
      background: #fffef9;
      overflow: hidden;
      transition: border-color .16s ease, box-shadow .16s ease, background .16s ease;
    }
    .sort-lane.drop-active {
      border-color: #8db99a;
      background: #f5fbf4;
      box-shadow: inset 0 0 0 1px rgba(31, 111, 76, 0.12);
    }
    .sort-lane-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
      padding: 11px 12px;
      border-bottom: 1px solid rgba(222, 214, 199, 0.76);
      background: #faf5ea;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }
    .sort-lane-head b {
      display: block;
      color: #2f362f;
      font-size: 14px;
      line-height: 1.25;
    }
    .sort-lane-head span {
      display: block;
      margin-top: 2px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
    }
    .sort-lane-count {
      flex: 0 0 auto;
      min-width: 30px;
      height: 24px;
      display: inline-grid;
      place-items: center;
      border-radius: 999px;
      background: #fffdf7;
      color: var(--accent);
      border: 1px solid #d9caa8;
      font-size: 12px;
      font-weight: 850;
    }
    .sort-card-list {
      display: grid;
      gap: 8px;
      padding: 10px;
    }
    .sort-card {
      display: grid;
      gap: 8px;
      border: 1px solid rgba(222, 214, 199, 0.86);
      border-radius: 8px;
      background: #fffdf7;
      padding: 10px;
      cursor: grab;
      box-shadow: 0 5px 14px rgba(92, 75, 44, 0.05);
    }
    .sort-card:active { cursor: grabbing; }
    .sort-card.dragging {
      opacity: .5;
      box-shadow: none;
    }
    .sort-card-top {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 8px;
      align-items: start;
    }
    .sort-seq {
      min-width: 34px;
      height: 26px;
      display: inline-grid;
      place-items: center;
      border-radius: 999px;
      background: #edf6ed;
      color: var(--accent);
      font-size: 12px;
      font-weight: 850;
    }
    .sort-card-title b {
      display: block;
      color: #253129;
      font-size: 14px;
      line-height: 1.32;
      overflow-wrap: anywhere;
    }
    .sort-card-title .mini {
      display: block;
      margin-top: 3px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .sort-card-facts {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 74px minmax(0, 1fr);
      gap: 6px;
      align-items: stretch;
    }
    .sort-fact.left-fact { grid-column: 1; }
    .sort-fact.right-fact { grid-column: 3; }
    .sort-fact {
      min-width: 0;
      padding: 6px 8px;
      border: 1px solid rgba(222, 214, 199, 0.66);
      border-radius: 7px;
      background: rgba(251, 248, 240, 0.74);
      font-size: 12px;
      line-height: 1.42;
    }
    .sort-fact b {
      display: block;
      margin-bottom: 2px;
      color: #6b604e;
      font-size: 11px;
      white-space: nowrap;
    }
    .sort-fact span {
      display: block;
      color: #333a33;
      overflow-wrap: anywhere;
    }
    .sort-card-risk-column {
      grid-column: 2;
      grid-row: 1 / span 3;
      display: grid;
      align-content: center;
      justify-items: center;
      gap: 5px;
      min-width: 0;
      padding: 6px 4px;
      border: 1px solid rgba(222, 214, 199, 0.72);
      border-radius: 7px;
      background: #fffaf0;
      text-align: center;
    }
    .sort-card-risk-column b {
      color: #7c705c;
      font-size: 10px;
      line-height: 1.1;
      font-weight: 860;
    }
    .sort-card-risk-column .risk-badge {
      width: 100%;
      min-width: 0;
      justify-content: center;
      white-space: nowrap;
    }
    .sort-card-actions {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 6px;
      align-items: center;
      justify-content: start;
      max-width: 380px;
    }
    .sort-move-row,
    .sort-secondary-row {
      display: grid;
      gap: 6px;
      align-items: center;
      justify-content: start;
    }
    .sort-move-row {
      grid-template-columns: 48px 48px minmax(158px, 1fr);
      width: min(100%, 300px);
    }
    .sort-secondary-row {
      grid-template-columns: 86px 52px 52px;
      width: min(100%, 204px);
    }
    .sort-card-actions button,
    .sort-card-actions .charter-link {
      width: auto;
      min-width: 0;
      min-height: 26px;
      height: 26px;
      padding: 0 8px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
    }
    .sort-card-actions .move-to-control {
      grid-column: auto;
      width: 100%;
      height: 26px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 0 6px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fffdf7;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
    }
    .sort-card-actions .move-to-control input {
      width: 38px;
      height: 20px;
      padding: 0 4px;
      font-size: 11px;
    }
    .sort-card-actions .move-to-control button {
      height: 20px;
      padding: 0 5px;
    }
    .sort-card-actions .delete-button {
      width: 100%;
    }
    .sort-empty {
      padding: 16px 12px;
      border: 1px dashed #d6c8ad;
      border-radius: 8px;
      background: #fffaf0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      text-align: center;
    }
    .major-workbench {
      display: grid;
      gap: 14px;
    }
    .major-toolbar {
      display: grid;
      grid-template-columns: minmax(220px, 1fr) 180px auto auto;
      gap: 10px;
      align-items: center;
    }
    .major-source {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 12px;
      border: 1px solid #e5d8bf;
      border-radius: 9px;
      background: #fffaf0;
      color: #6f6048;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 12px;
      font-weight: 700;
    }
    .major-groups {
      display: grid;
      gap: 12px;
      max-height: 560px;
      overflow: auto;
      padding-right: 4px;
    }
    .major-group {
      border: 1px solid var(--line);
      border-radius: 9px;
      background: #fffef9;
      overflow: hidden;
    }
    .major-group-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      background: #fbf8f0;
    }
    .major-options {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      padding: 12px;
    }
    .major-option {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 8px;
      align-items: flex-start;
      min-height: 64px;
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fffdf7;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 13px;
      cursor: pointer;
    }
    .major-option:hover { background: #f7f0df; }
    .major-option.selected {
      border-color: #95bfa1;
      background: #edf6ed;
    }
    .major-option input {
      width: 17px;
      height: 17px;
      margin-top: 2px;
      accent-color: var(--accent);
    }
    .major-option b {
      display: block;
      color: #273029;
      font-size: 13px;
    }
    .major-option span {
      color: #857b6a;
      font-size: 11px;
    }
    .empty-row {
      padding: 22px 16px !important;
      color: var(--muted);
      text-align: center;
      font-weight: 760;
    }
    .pagination {
      display: flex;
      align-items: center;
      justify-content: flex-start;
      flex-wrap: wrap;
      gap: 8px 10px;
      padding: 7px 9px;
      border: 1px solid rgba(222, 214, 199, 0.78);
      border-top: 0;
      border-radius: 0 0 9px 9px;
      background: #fbf8f0;
      color: var(--muted);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 11px;
      font-weight: 700;
    }
    .pagination-summary {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
      color: #766c5e;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .pagination-summary strong {
      color: var(--graphite);
      font-weight: 860;
    }
    .pagination-summary span {
      color: #877d6d;
      font-size: 10px;
      font-weight: 760;
    }
    .pagination-actions {
      display: flex;
      align-items: center;
      gap: 5px;
      flex-wrap: nowrap;
      justify-content: flex-start;
      min-width: 0;
    }
    .pagination button {
      width: 26px;
      height: 24px;
      min-width: 26px;
      padding: 0;
      border-color: var(--line);
      background: #fffdf7;
      color: var(--graphite);
      box-shadow: none;
      font-size: 15px;
      line-height: 1;
    }
    .pagination button:hover:not(:disabled) {
      background: #edf6ed;
      border-color: #9fc0a9;
      color: var(--accent);
    }
    .pagination button:disabled {
      cursor: not-allowed;
      opacity: 0.45;
    }
    .page-size-control {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      color: #6f6657;
      font-size: 10px;
      font-weight: 760;
      white-space: nowrap;
    }
    .page-size-control select {
      width: 72px;
      height: 24px;
      padding: 0 22px 0 7px;
      border-radius: 7px;
      border: 1px solid var(--line);
      background: #fffdf7;
      color: var(--graphite);
      font-size: 10px;
      font-weight: 800;
    }
    .page-jump-control {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      color: #6f6657;
      font-size: 10px;
      font-weight: 760;
      white-space: nowrap;
    }
    .page-jump-control input {
      width: 48px;
      height: 24px;
      padding: 0 5px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fffdf7;
      color: var(--graphite);
      font-size: 10px;
      font-weight: 800;
      text-align: center;
    }
    .page-jump-control button {
      width: auto;
      min-width: 40px;
      height: 24px;
      padding: 0 8px;
      font-size: 10px;
      font-weight: 800;
    }
    .heat {
      color: var(--danger);
      font-weight: 800;
    }
    .system-bar {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 18px;
      align-items: center;
      margin-top: 18px;
      padding: 13px 18px;
      border-top: 1px solid #d9caa8;
      background: rgba(232, 220, 197, 0.58);
      box-shadow: inset 0 1px rgba(255,255,255,0.65);
    }
    .bar-features {
      display: flex;
      flex-wrap: wrap;
      gap: 24px;
      color: #6d6558;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      font-size: 13px;
      font-weight: 760;
    }
    .bar-actions {
      display: flex;
      gap: 12px;
    }
    .bar-actions button {
      width: auto;
      min-width: 138px;
      background: #fffdf7;
      border-color: #c9bda8;
      color: var(--graphite);
      box-shadow: 0 8px 20px rgba(92, 75, 44, 0.10);
    }
    .bar-actions button.primary-lite {
      background: #f2e3c8;
      border-color: #c9a85c;
      color: #473d2b;
    }
    .delete-button {
      color: var(--danger) !important;
      border-color: #efc6bf !important;
      background: #fff8f5 !important;
    }
    @media print {
      body { background: #fff; }
      header, .notice, .controls, .step-tabs, .system-bar, .footer, .dialog-backdrop, .progress-backdrop, .settings-slide-backdrop, .settings-slide-panel { display: none !important; }
      .selection-drawer, .selection-drawer-backdrop, .cart-dock-button { display: none !important; }
      .shell { max-width: none; padding: 0; }
      .grid { display: block; }
      aside { position: static; box-shadow: none; margin-bottom: 12px; }
      .panel { break-inside: avoid; box-shadow: none; margin-bottom: 12px; }
      .step-panel[hidden] { display: block; }
    }
    @media (max-width: 1180px) {
      .controls { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
      .settings-toggle-row { grid-template-columns: 1fr; }
      .settings-slide-panel {
        width: min(560px, 86vw);
      }
      .controls > label {
        min-height: auto;
        padding: 0;
        border-right: 0;
      }
      .generate-wrap {
        padding-left: 0;
        align-self: end;
      }
      .generate-wrap button {
        min-width: 0;
      }
      .major-toolbar { grid-template-columns: 1fr 180px; }
      .major-options { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .commercial-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .backtest-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .grid.cart-pinned {
        grid-template-columns: minmax(0, 1fr) minmax(300px, 32vw);
        grid-template-areas: "main aside";
      }
      .step-tabs { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      aside { position: static; }
      header { grid-template-columns: 1fr; }
      .stamp { min-width: 0; text-align: left; }
    }
    .recommendation-table .num-cell { width: 5%; }
    .recommendation-table .option-cell { width: 21%; }
    .recommendation-table .risk-cell { width: 7%; }
    .recommendation-table .score-cell { width: 10%; }
    .recommendation-table .match-cell { width: 16%; }
    .recommendation-table .review-cell { width: 21%; }
    .recommendation-table .action-cell { width: 20%; }
    .recommendation-table {
      border-collapse: separate;
      border-spacing: 0;
    }
    .recommendation-table th {
      border-bottom: 1px solid #d8ccb6;
      background: #f7f1e5;
      color: #695f4f;
      font-size: 12px;
    }
    .recommendation-table td {
      padding: 14px 12px;
      border-bottom-color: rgba(222, 214, 199, 0.62);
    }
    .recommendation-table tbody tr:nth-child(even) td { background: #fffbf2; }
    .recommendation-table tbody tr:hover td { background: #f4f8ef; }
    .recommendation-table .school-cell {
      align-items: flex-start;
    }
    .recommendation-table .compact-lines {
      display: grid;
      gap: 7px;
    }
    .recommendation-table .compact-line {
      padding: 6px 8px;
      border: 1px solid rgba(222, 214, 199, 0.68);
      border-radius: 7px;
      background: rgba(255, 253, 247, 0.78);
    }
    .recommendation-table .action-cell .sort-actions {
      align-items: center;
    }
    .sort-actions {
      display: grid;
      grid-template-columns: 28px 28px minmax(82px, 1fr);
      gap: 4px;
      justify-content: center;
      align-items: center;
    }
    .recommendation-table .sort-actions button {
      width: 28px;
      min-width: 0;
      height: 24px;
      padding: 0;
      border-radius: 5px;
      font-size: 10px;
      line-height: 1;
    }
    .recommendation-table .sort-actions .move-to-control {
      grid-column: span 1;
      width: 100%;
      height: 24px;
      padding: 0 2px;
      gap: 2px;
      justify-content: center;
      font-size: 10px;
    }
    .recommendation-table .sort-actions .move-to-control input {
      width: 28px;
      height: 18px;
      padding: 0 2px;
      font-size: 10px;
    }
    .recommendation-table .sort-actions .move-to-control button {
      width: 18px;
      height: 18px;
      font-size: 10px;
    }
    .recommendation-table .sort-actions .charter-link {
      grid-column: span 2;
      width: 100%;
      min-height: 24px;
      padding: 1px 4px;
      font-size: 10px;
    }
    .recommendation-table .match-cell,
    .recommendation-table .review-cell {
      min-width: 0;
    }
    @media (max-width: 1500px) {
      .matched-university-wrap table.matched-table {
        min-width: 1040px;
      }
      .recommendation-table,
      .recommendation-table thead,
      .recommendation-table tbody,
      .recommendation-table tr,
      .recommendation-table th,
      .recommendation-table td {
        display: block;
        width: 100% !important;
      }
      .recommendation-table thead {
        display: none;
      }
      .recommendation-table tr {
        display: grid;
        grid-template-columns: 52px minmax(180px, 1.16fr) 72px minmax(112px, 0.66fr) minmax(130px, 0.84fr) minmax(170px, 1.05fr) 156px;
        grid-template-areas:
          "num option risk score match review action";
        gap: 0;
        margin: 12px;
        padding: 0;
        border: 1px solid rgba(222, 214, 199, 0.84);
        border-radius: 9px;
        background: #fffef9;
        overflow: hidden;
      }
      .recommendation-table td {
        width: auto !important;
        min-width: 0;
        padding: 12px 10px;
        border-right: 1px solid rgba(222, 214, 199, 0.46);
        border-bottom: 0;
        background: transparent !important;
      }
      .recommendation-table td:last-child {
        border-right: 0;
      }
      .recommendation-table td::before {
        display: block;
        margin-bottom: 4px;
        color: #8a7d68;
        font-size: 11px;
        font-weight: 800;
      }
      .recommendation-table .num-cell { grid-area: num; }
      .recommendation-table .option-cell { grid-area: option; }
      .recommendation-table .risk-cell { grid-area: risk; }
      .recommendation-table .score-cell { grid-area: score; }
      .recommendation-table .match-cell { grid-area: match; }
      .recommendation-table .review-cell { grid-area: review; }
      .recommendation-table .action-cell { grid-area: action; }
      .recommendation-table td.num-cell::before { content: "序号"; }
      .recommendation-table td.option-cell::before { content: "专业 + 院校"; }
      .recommendation-table td.risk-cell::before { content: "冲稳保"; }
      .recommendation-table td.score-cell::before { content: "参考位次"; }
      .recommendation-table td.match-cell::before { content: "匹配依据"; }
      .recommendation-table td.review-cell::before { content: "计划/章程"; }
      .recommendation-table td.action-cell::before { content: "操作"; }
      .recommendation-table .school-cell {
        max-width: 100%;
      }
      .recommendation-table .school-name {
        font-size: 15px;
        line-height: 1.35;
      }
      .recommendation-table .major-name,
      .recommendation-table .mini,
      .recommendation-table .identity-line {
        font-size: 12px;
      }
      .recommendation-table .compact-lines {
        gap: 6px;
      }
      .recommendation-table .compact-line {
        display: grid;
        grid-template-columns: 72px minmax(0, 1fr);
        gap: 8px;
        align-items: start;
        font-size: 12px;
        line-height: 1.48;
      }
      .recommendation-table .compact-line b {
        text-align: left;
      }
      .recommendation-table .compact-line span {
        overflow-wrap: anywhere;
        word-break: normal;
      }
      .recommendation-table .table-actions {
        justify-content: flex-start;
      }
      .recommendation-table .goto-row {
        flex-wrap: wrap;
      }
    }
    @media (max-width: 1180px) {
      .strategy-description-panel .compare-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .match-toolbar {
        grid-template-columns: 1fr auto auto;
      }
      .match-toolbar > input {
        grid-column: 1 / -1;
      }
      .sort-smart-strip {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .sort-board {
        grid-template-columns: 1fr;
      }
      .recommendation-table tr {
        grid-template-columns: 48px minmax(0, 1fr) 118px;
        grid-template-areas:
          "num option action"
          "risk score action"
          "match match match"
          "review review review";
      }
      .recommendation-table .sort-actions {
        justify-content: end;
      }
    }
    @media (max-width: 760px) {
      .shell { padding: 14px; }
      h1 { font-size: 26px; }
      .controls, .metrics, .checklist { grid-template-columns: 1fr; }
      .grid {
        grid-template-columns: 1fr;
        grid-template-areas: "main";
      }
      .grid.cart-pinned {
        grid-template-areas: "main" "aside";
      }
      aside {
        position: static;
      }
      .cart-actions,
      .selection-drawer-footer {
        grid-template-columns: 1fr;
      }
      .selection-drawer {
        width: 100vw;
      }
      .drawer-item {
        min-width: 700px;
      }
      .settings-slide-panel {
        width: 100vw;
        max-width: 100vw;
      }
      .settings-trigger-row {
        grid-template-columns: 1fr;
      }
      .cart-dock-button {
        right: 12px;
        bottom: 74px;
      }
      .sort-workbench {
        padding: 10px;
      }
      .sort-smart-strip,
      .sort-card-facts {
        grid-template-columns: 1fr;
      }
      .sort-card-top {
        grid-template-columns: auto minmax(0, 1fr);
      }
      .sort-card-top .risk-badge {
        grid-column: 1 / -1;
        justify-self: start;
      }
      .sort-card-actions {
        max-width: none;
        grid-template-columns: minmax(0, 1fr);
      }
      .sort-move-row {
        grid-template-columns: 46px 46px minmax(146px, 1fr);
        width: 100%;
      }
      .sort-secondary-row {
        width: 100%;
      }
      .sort-card-actions .delete-button {
        grid-column: auto;
      }
      .selection-drawer-head,
      .selection-drawer .drawer-count-grid,
      .selection-drawer-body,
      .selection-drawer-footer {
        padding-left: 14px;
        padding-right: 14px;
      }
      .generate-wrap {
        justify-self: stretch;
        width: 100%;
        padding-left: 0;
        transform: none;
      }
      .step-tabs { grid-template-columns: 1fr; }
      .step-tab {
        min-height: 44px;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
      .step-tab:last-child { border-bottom: 0; }
      .profile-grid { grid-template-columns: 1fr; }
      .tag-toolbar { grid-template-columns: 1fr; }
      .major-toolbar, .major-options { grid-template-columns: 1fr; }
      .commercial-grid, .backtest-grid, .compare-grid, .audit-grid { grid-template-columns: 1fr; }
      .match-toolbar {
        grid-template-columns: 1fr;
      }
      .free-select-toggle {
        justify-content: center;
      }
      .audit-row { grid-template-columns: 1fr; }
      .header-actions {
        min-width: 0;
        align-items: flex-start;
      }
      .header-action-row {
        justify-content: flex-start;
      }
      .header-warning {
        max-width: none;
        text-align: left;
      }
      .title-filter-pills {
        justify-content: flex-start;
        max-width: none;
      }
      .system-bar { grid-template-columns: 1fr; }
      .bar-actions { flex-wrap: wrap; }
      .bar-actions button {
        flex: 1 1 120px;
        min-width: 0;
      }
      .legend-row {
        grid-template-columns: 12px minmax(0, 1fr);
        align-items: start;
      }
      .legend-row b {
        grid-column: 2;
        justify-self: start;
      }
      .risk-legend .calc-value {
        white-space: normal;
      }
      .dialog-actions { justify-content: stretch; }
      .dialog-actions button { flex: 1 1 120px; }
      table, thead, tbody, tr, th, td { display: block; width: 100% !important; }
      .table-wrap table { min-width: 0; }
      thead { display: none; }
      tr { border-bottom: 1px solid var(--line); }
      td { border-bottom: 0; }
      td::before { display: block; color: var(--muted); font-size: 12px; margin-bottom: 2px; }
      td.num-cell::before { content: "序号"; }
      td.option-cell::before { content: "志愿"; }
      td.risk-cell::before { content: "冲稳保"; }
      td.score-cell::before { content: "参考位次"; }
      td.match-cell::before { content: "匹配依据"; }
      td.review-cell::before { content: "计划/章程"; }
      .matched-university-wrap .matched-table tbody,
      .recommendation-table tbody {
        display: grid;
        gap: 12px;
        padding: 10px;
      }
      .matched-university-wrap .matched-table tr,
      .recommendation-table tr {
        display: grid;
        grid-template-columns: 1fr;
        grid-template-areas: none;
        margin: 0;
      }
      .recommendation-table .num-cell,
      .recommendation-table .option-cell,
      .recommendation-table .risk-cell,
      .recommendation-table .score-cell,
      .recommendation-table .match-cell,
      .recommendation-table .review-cell,
      .recommendation-table .action-cell {
        grid-area: auto;
      }
      .matched-university-wrap .matched-table td,
      .recommendation-table td {
        border-right: 0;
        border-bottom: 1px solid rgba(222, 214, 199, 0.52);
      }
      .matched-university-wrap .matched-table td:last-child,
      .recommendation-table td:last-child {
        border-bottom: 0;
      }
      .matched-university-wrap table.matched-table {
        display: table;
        width: 100% !important;
        min-width: 1040px;
      }
      .matched-university-wrap .matched-table thead {
        display: table-header-group;
      }
      .matched-university-wrap .matched-table tbody {
        display: table-row-group;
        padding: 0;
      }
      .matched-university-wrap .matched-table tr {
        display: table-row;
        margin: 0;
        border-bottom: 0;
      }
      .matched-university-wrap .matched-table th,
      .matched-university-wrap .matched-table td {
        display: table-cell;
        width: auto !important;
        border-right: 0;
      }
      .matched-university-wrap .matched-table td {
        border-bottom: 1px solid rgba(222, 214, 199, 0.58);
      }
      .matched-university-wrap .matched-table td::before {
        display: none;
        content: none;
      }
      .matched-university-wrap .matched-table th:nth-child(1),
      .matched-university-wrap .matched-table td:nth-child(1) { width: 21.2% !important; }
      .matched-university-wrap .matched-table th:nth-child(2),
      .matched-university-wrap .matched-table td:nth-child(2) { width: 7% !important; }
      .matched-university-wrap .matched-table th:nth-child(3),
      .matched-university-wrap .matched-table td:nth-child(3) { width: 12% !important; }
      .matched-university-wrap .matched-table th:nth-child(4),
      .matched-university-wrap .matched-table td:nth-child(4) { width: 6% !important; }
      .matched-university-wrap .matched-table th:nth-child(5),
      .matched-university-wrap .matched-table td:nth-child(5) { width: 9% !important; }
      .matched-university-wrap .matched-table th:nth-child(6),
      .matched-university-wrap .matched-table td:nth-child(6) { width: 15% !important; }
      .matched-university-wrap .matched-table th:nth-child(7),
      .matched-university-wrap .matched-table td:nth-child(7) { width: 10% !important; }
      .matched-university-wrap .matched-table th:nth-child(8),
      .matched-university-wrap .matched-table td:nth-child(8) { width: 7% !important; }
      .matched-university-wrap .matched-table th:nth-child(9),
      .matched-university-wrap .matched-table td:nth-child(9) { width: 12.8% !important; }
      .sort-card-facts {
        grid-template-columns: 1fr;
      }
      .sort-fact.left-fact,
      .sort-fact.right-fact,
      .sort-card-risk-column {
        grid-column: 1;
      }
      .sort-card-risk-column {
        grid-row: auto;
        grid-template-columns: auto minmax(0, 1fr);
        justify-items: start;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="brand">
        <div class="brand-logo" aria-hidden="true">
          <svg viewBox="0 0 64 64" role="img" focusable="false">
            <defs>
              <linearGradient id="brandLogoGradient" x1="12" y1="6" x2="52" y2="58">
                <stop stop-color="#2e825d"/>
                <stop offset="1" stop-color="#113f2c"/>
              </linearGradient>
            </defs>
            <rect x="5" y="5" width="54" height="54" rx="16" fill="url(#brandLogoGradient)"/>
            <path d="M20 39.5 28.5 48 46 19" fill="none" stroke="#f4d37b" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M18 18h18M18 27h13" stroke="#fff7df" stroke-width="4" stroke-linecap="round"/>
          </svg>
        </div>
        <div>
          <h1>志愿参考系统</h1>
          <div class="brand-en">VOLUNTEER REFERENCE SYSTEM</div>
        </div>
      </div>
      <div class="data-brief">
        <span>历史投档 2023-2025</span>
        <span class="mini">山东普通类常规批</span>
      </div>
      <div class="header-actions">
        <div class="header-action-row">
          <span class="data-updated-chip" id="latestDataUpdatedAt">最新数据更新时间：读取中</span>
          <button type="button" data-info="source">数据源管理</button>
          <button type="button" data-info="guide">使用说明书</button>
          <button type="button" data-info="compliance">须知与免责</button>
          <button type="button" data-info="version">V1.0 版本</button>
        </div>
        <p class="header-warning">重要提示：系统输出结果仅供参考，用户必须自行核对山东省教育招生考试院、院校官方招生计划和招生章程。</p>
      </div>
    </header>

    <form class="controls" id="form">
      <label>2026 全省位次
        <input class="rank-input" id="rankInput" name="rank" inputmode="numeric" pattern="[1-9][0-9]*" min="1" step="1" placeholder="请输入全省位次" required>
      </label>
      <label>选科（限选3科）
        <input type="hidden" name="subjects" id="subjectsValue" value="物理,化学,生物">
        <button type="button" class="choice-button" id="subjectButton">物理、化学、生物</button>
      </label>
      <label class="interest-control">
        <span class="label-row">
          <span>专业选择</span>
          <button type="button" class="inline-button" id="interestTestButton">兴趣测评</button>
        </span>
        <input type="hidden" name="interests" id="interestsValue" value="">
        <button type="button" class="tag-field" id="interestPickerButton"></button>
      </label>
      <input type="hidden" name="strategy" value="balanced">
      <label>志愿数
        <input class="control-select" name="targetSize" type="text" inputmode="numeric" pattern="[1-9][0-9]*" list="targetSizePresets" value="96" placeholder="可输入 100、200">
        <datalist id="targetSizePresets">
          <option value="96"></option>
          <option value="100"></option>
          <option value="200"></option>
          <option value="80"></option>
          <option value="60"></option>
          <option value="40"></option>
        </datalist>
      </label>
      <div class="custom-plan-hidden" aria-hidden="true">
        <input type="hidden" name="customQuotaHighChallenge" value="2">
        <input type="hidden" name="customQuotaChallenge" value="16">
        <input type="hidden" name="customQuotaLeanSteady" value="24">
        <input type="hidden" name="customQuotaSteady" value="30">
        <input type="hidden" name="customQuotaSafe" value="19">
        <input type="hidden" name="customQuotaStrongSafe" value="5">
      </div>
      <div class="generate-wrap">
        <div class="generate-actions">
          <button type="submit" id="generatePlanButton">生成方案</button>
          <button type="button" class="secondary-report-button" id="previewReportButton">预览报告</button>
          <button type="button" class="secondary-report-button" id="exportPdfButton">导出报告</button>
        </div>
        <div class="settings-trigger-row">
          <button type="button" id="openStrategySettings">
            <span class="settings-trigger-title">方案设定</span>
            <span class="settings-trigger-note" id="strategySummaryNote">当前：均衡预设</span>
          </button>
          <button type="button" id="openProfileSettings">
            <span class="settings-trigger-title">详细筛选条件</span>
            <span class="settings-trigger-note" id="filterSummaryNote">默认筛选</span>
          </button>
        </div>
        <div class="generate-note" id="settingsDirtyBanner"></div>
      </div>
      <div class="settings-slide-backdrop" id="settingsSlideBackdrop"></div>
      <aside class="settings-slide-panel" id="settingsSlidePanel" role="dialog" aria-modal="true" aria-labelledby="settingsSlideTitle" aria-hidden="true">
        <div class="settings-slide-head">
          <div>
            <h2 id="settingsSlideTitle">方案设定</h2>
            <div class="mini" id="settingsSlideSummary">当前：均衡预设</div>
          </div>
          <button type="button" id="closeSettingsSlide">关闭</button>
        </div>
        <div class="settings-slide-body">
        <section class="strategy-description-panel settings-slide-content" data-settings-panel="strategy">
          <div class="mini" id="strategyDescriptionText">当前使用均衡预设；前三个为预设方案，自定义方案可直接调整冲稳保比例。</div>
          <div class="compare-grid" id="strategyCompareCards"></div>
        </section>
        <section class="profile-panel settings-slide-content" data-settings-panel="profile" hidden>
          <div class="profile-grid">
            <label>决策优先级
              <select name="priority">
                <option value="balanced">均衡</option>
                <option value="school">院校层次优先</option>
                <option value="major">专业匹配优先</option>
                <option value="city">城市优先</option>
                <option value="cost">成本优先</option>
              </select>
            </label>
            <label>浮动分
              <input name="bandWidth" inputmode="numeric" value="20">
            </label>
            <label>学费上限
              <input name="maxTuition" inputmode="numeric" placeholder="例如 12000">
            </label>
            <label class="wide-field">偏好城市
              <input name="preferredCities" placeholder="济南 青岛 北京 上海">
            </label>
            <label class="wide-field">排除城市
              <input name="blockedCities" placeholder="不想去的城市">
            </label>
            <label class="wide-field">排斥关键词
              <input name="avoidKeywords" placeholder="护理 中外合作 高收费">
            </label>
            <label class="checkline"><input type="checkbox" name="requirePublicUndergrad"> 只看公办本科</label>
            <label class="checkline"><input type="checkbox" name="requireDoubleFirstClass"> 只看双一流</label>
            <label class="checkline"><input type="checkbox" name="require985"> 只看985</label>
            <label class="checkline"><input type="checkbox" name="require211"> 只看211</label>
            <label class="checkline"><input type="checkbox" name="allowPrivate"> 接受民办院校</label>
            <label class="checkline"><input type="checkbox" name="allowSinoForeign"> 接受中外合作/高收费项目</label>
          </div>
        </section>
        </div>
      </aside>
    </form>

    <div class="dialog-backdrop" id="subjectDialog" role="dialog" aria-modal="true" aria-labelledby="subjectDialogTitle">
      <div class="dialog">
        <div class="dialog-head">
          <div>
            <h2 id="subjectDialogTitle">选择 3 门选科</h2>
            <div class="mini">必须且只能选择 3 门；专业选科要求是所选科目的子集时才允许进入候选。</div>
          </div>
          <button type="button" class="secondary-button" id="subjectClose">关闭</button>
        </div>
        <div class="dialog-body">
          <div class="subject-grid" id="subjectGrid"></div>
          <div class="error-text" id="subjectError"></div>
        </div>
        <div class="dialog-actions">
          <button type="button" class="secondary-button" id="subjectReset">重选</button>
          <button type="button" id="subjectConfirm">确认选科</button>
        </div>
      </div>
    </div>

    <div class="dialog-backdrop interest-picker-dialog" id="interestPickerDialog" role="dialog" aria-modal="true" aria-labelledby="interestPickerDialogTitle">
      <div class="dialog">
        <div class="dialog-head">
          <div>
            <h2 id="interestPickerDialogTitle">选择专业</h2>
            <div class="mini">优先使用教育部本科专业目录标准名称，并补充山东普通类常规批招生专业名称。</div>
          </div>
          <button type="button" class="secondary-button" id="interestPickerClose">关闭</button>
        </div>
        <div class="dialog-body">
          <div class="tag-toolbar">
            <input id="interestSearch" placeholder="搜索标准专业或山东招生专业：计算机科学与技术、临床医学、计算机类(网络安全)">
            <div class="mini" id="interestCount">已选 0 项</div>
          </div>
          <div class="tag-groups" id="interestOptionList"></div>
          <div class="error-text" id="interestPickerError"></div>
        </div>
        <div class="dialog-actions">
          <button type="button" class="secondary-button danger-text-button" id="interestPickerClear">清空</button>
          <button type="button" id="interestPickerConfirm">确认专业</button>
        </div>
      </div>
    </div>

    <div class="dialog-backdrop" id="interestDialog" role="dialog" aria-modal="true" aria-labelledby="interestDialogTitle">
      <div class="dialog" style="width:min(760px, 100%);">
        <div class="dialog-head">
          <div>
            <h2 id="interestDialogTitle">专业选择引导测试</h2>
            <div class="mini">24 个情境题，基于 RIASEC 职业兴趣维度，结果会转成推荐专业选择。</div>
          </div>
          <button type="button" class="secondary-button" id="interestClose">关闭</button>
        </div>
        <div class="dialog-body">
          <div class="notice" style="margin:0 0 12px;">按“这件事像不像你真实愿意长期投入的方向”作答，不按当前成绩、家长期望或热门程度作答。</div>
          <div class="question-list" id="interestQuestions"></div>
          <div class="error-text" id="interestError"></div>
          <div class="result-box" id="interestResult"></div>
        </div>
        <div class="dialog-actions">
          <button type="button" class="secondary-button" id="interestClear">重新作答</button>
          <button type="button" class="secondary-button" id="interestCalculate">生成结果</button>
          <button type="button" id="interestApply">确认填入</button>
        </div>
      </div>
    </div>

    <div class="progress-backdrop" id="progressOverlay" role="status" aria-live="polite">
      <div class="progress-card">
        <h2>正在生成志愿方案</h2>
        <div class="mini" id="progressText">正在校验输入条件</div>
        <div class="progress-track"><div class="progress-fill" id="progressFill"></div></div>
        <div class="progress-meta"><span id="progressStage">准备中</span><span id="progressPercent">0%</span></div>
      </div>
    </div>

    <div class="dialog-backdrop" id="infoDialog" role="dialog" aria-modal="true" aria-labelledby="infoDialogTitle">
      <div class="dialog" style="width:min(640px, 100%);">
        <div class="dialog-head">
          <div>
            <h2 id="infoDialogTitle">系统信息</h2>
            <div class="mini" id="infoDialogSub">系统信息</div>
          </div>
          <button type="button" class="secondary-button" id="infoDialogClose">关闭</button>
        </div>
        <div class="dialog-body" id="infoDialogBody"></div>
      </div>
    </div>

    <div class="data-source-workbench-backdrop" id="dataSourceWorkbenchBackdrop"></div>
    <section class="data-source-workbench" id="dataSourceWorkbench" role="dialog" aria-modal="true" aria-labelledby="dataSourceWorkbenchTitle" aria-hidden="true">
      <div class="data-source-workbench-head">
        <div>
          <h2 id="dataSourceWorkbenchTitle">数据源管理</h2>
          <div class="mini">年度数据工作台 · 导入、完整性、原始记录编辑</div>
        </div>
        <button type="button" class="secondary-button" id="dataSourceWorkbenchClose" aria-label="关闭数据源管理">×</button>
      </div>
      <div class="data-source-workbench-body" id="dataSourceWorkbenchBody"></div>
      <div class="data-source-workbench-footer">年度可新增；所有修改均保留备份；正式填报前仍须核对官方来源。</div>
    </section>

    <div class="dialog-backdrop report-preview-dialog" id="reportPreviewDialog" role="dialog" aria-modal="true" aria-labelledby="reportPreviewTitle">
      <div class="dialog">
        <div class="dialog-head">
          <div>
            <h2 id="reportPreviewTitle">报告预览</h2>
            <div class="mini">预览内容仅供参考，正式填报前必须逐项核对官方招生计划与招生章程。</div>
          </div>
          <button type="button" class="secondary-button" id="reportPreviewClose">关闭</button>
        </div>
        <div class="dialog-body">
          <iframe class="report-preview-frame" id="reportPreviewFrame" title="志愿参考报告预览"></iframe>
        </div>
      </div>
    </div>

    <div class="grid">
      <aside class="selection-cart-rail" aria-label="已选志愿清单">
        <section class="rail-section cart-summary-panel">
          <div class="cart-summary-head">
            <div>
              <h2>已选清单</h2>
              <div class="mini" id="selectionCartHint">从左侧匹配列表勾选，右侧实时汇总。</div>
            </div>
            <span class="cart-total-badge" id="selectionCartTotal">已选 0/96</span>
          </div>
          <div class="cart-count-grid" aria-label="冲稳保已选数量">
            <button type="button" class="cart-count challenge" data-cart-risk-filter="challenge"><b id="selectionCartChallenge">0</b><span>冲</span></button>
            <button type="button" class="cart-count steady" data-cart-risk-filter="steady"><b id="selectionCartSteady">0</b><span>稳</span></button>
            <button type="button" class="cart-count safe" data-cart-risk-filter="safe"><b id="selectionCartSafe">0</b><span>保</span></button>
          </div>
          <div class="cart-stack" id="selectionCartStack" aria-hidden="true"></div>
          <div class="cart-alert-row">
            <span id="selectionReviewChip">复核 0</span>
            <span id="selectionCharterChip">章程 0</span>
          </div>
          <div class="cart-preview-list" id="selectionCartPreview">
            <div class="cart-empty">还没有加入志愿，先在左侧列表勾选。</div>
          </div>
          <div class="cart-actions">
            <button type="button" id="openSelectionDrawer">查看清单</button>
            <button type="button" class="secondary-button" id="unpinSelectionCart">自动隐藏</button>
            <button type="button" class="secondary-button danger-text-button" id="cartClearSelected">清空</button>
          </div>
        </section>
      </aside>

      <main>
        <section class="panel step-panel" data-step-panel="2">
          <div class="step-title"><h2>选择学校专业</h2><div class="filter-pills title-filter-pills" id="matchedFilters"></div></div>
          <div class="panel-body">
            <div class="match-toolbar">
              <input id="candidateSearch" placeholder="空格分隔多个关键词：山东大学 临床医学、北京 计算机、口腔医学等">
              <div class="free-select-field">
                <label class="free-select-toggle"><input type="checkbox" id="freeSelectionToggle"> 自由选择</label>
                <span class="help-icon free-select-help" tabindex="0" title="勾选后，搜索学校和专业不再受当前冲稳保方案限制，会在全部候选中检索，适合临时加入特别关注的学校或专业；取消勾选后恢复按方案筛选。" data-tooltip="勾选后，搜索学校和专业不再受当前冲稳保方案限制，会在全部候选中检索，适合临时加入特别关注的学校或专业；取消勾选后恢复按方案筛选。">?</span>
              </div>
              <button type="button" class="secondary-button" id="clearCandidateSearch">清空搜索</button>
              <button type="button" class="secondary-button danger-text-button" id="clearSelectedCandidates">清空已选</button>
            </div>
            <div class="table-wrap matched-university-wrap">
              <table class="matched-table">
                <thead>
                  <tr>
                    <th>院校专业 <span class="help-icon" tabindex="0" title="这里显示院校、专业、专业代码、校区、选科、学费和章程提醒。点开章程后还要以学校官方原文为准。" data-tooltip="这里显示院校、专业、专业代码、校区、选科、学费和章程提醒。点开章程后还要以学校官方原文为准。">?</span></th>
                    <th>院校层次 <span class="help-icon" tabindex="0" title="这里集中显示 985、211、双一流等院校层次标签。无特殊标签时按本科展示。" data-tooltip="这里集中显示 985、211、双一流等院校层次标签。无特殊标签时按本科展示。">?</span></th>
                    <th>学科评估及保研率 <span class="help-icon" tabindex="0" title="上方展示报考专业对应学科评估；下方展示学校或专业口径的保研率。若数据未接入则显示待接入，填报前需以学校官方公开信息为准。" data-tooltip="上方展示报考专业对应学科评估；下方展示学校或专业口径的保研率。若数据未接入则显示待接入，填报前需以学校官方公开信息为准。">?</span></th>
                    <th>所在地 <span class="help-icon" tabindex="0" title="学校或主要办学地点所在城市。部分专业可能有不同校区，具体以院校章程和招生计划为准。" data-tooltip="学校或主要办学地点所在城市。部分专业可能有不同校区，具体以院校章程和招生计划为准。">?</span></th>
                    <th>招生计划数 <span class="help-icon" tabindex="0" title="优先显示已接入的 2026 分专业招生计划人数；若官方计划未整理到该专业，显示按近年计划数估算的约值，正式填报前必须核对官方计划。" data-tooltip="优先显示已接入的 2026 分专业招生计划人数；若官方计划未整理到该专业，显示按近年计划数估算的约值，正式填报前必须核对官方计划。">?</span></th>
                    <th>近三年招录/最低位次 <span class="help-icon" tabindex="0" title="按 2023、2024、2025 三年列出该学校专业往年计划人数和投档最低位次，格式为：2025年:25人/1002位。" data-tooltip="按 2023、2024、2025 三年列出该学校专业往年计划人数和投档最低位次，格式为：2025年:25人/1002位。">?</span></th>
                    <th>成功率 <span class="help-icon" tabindex="0" title="成功率先按位次差距和风险等级限定区间：高冲5-18%、冲18-38%、稳中偏冲38-60%、稳60-78%、保78-92%、强保92-98%；专业匹配和稳定性只在区间内小幅调整。该数值不是官方录取承诺。" data-tooltip="成功率先按位次差距和风险等级限定区间：高冲5-18%、冲18-38%、稳中偏冲38-60%、稳60-78%、保78-92%、强保92-98%；专业匹配和稳定性只在区间内小幅调整。该数值不是官方录取承诺。">?</span></th>
                    <th>风险等级 <span class="help-icon" tabindex="0" title="把你的位次和历史参考位次比较后分档：差得较多是高冲/冲，接近是稳中偏冲，有余量是稳/保/强保。它只是风险提示。" data-tooltip="把你的位次和历史参考位次比较后分档：差得较多是高冲/冲，接近是稳中偏冲，有余量是稳/保/强保。它只是风险提示。">?</span></th>
                    <th>操作 <span class="help-icon" tabindex="0" title="点“加入”会把该项放入右侧已选清单；再次点击“已加入”会从清单移除。" data-tooltip="点“加入”会把该项放入右侧已选清单；再次点击“已加入”会从清单移除。">?</span></th>
                  </tr>
                </thead>
                <tbody id="matchedUniversityRows"><tr><td colspan="9" class="empty-row">无数据</td></tr></tbody>
              </table>
            </div>
            <div class="pagination" id="matchedPagination"></div>
          </div>
        </section>

      </main>
    </div>

    <div class="selection-drawer-backdrop" id="selectionDrawerBackdrop"></div>
    <div class="selection-drawer" id="selectionDrawer" role="dialog" aria-modal="true" aria-labelledby="selectionDrawerTitle" aria-hidden="true">
      <div class="selection-drawer-resize" id="selectionDrawerResize" role="separator" aria-orientation="vertical" aria-label="拖动调整已选志愿清单宽度"></div>
      <div class="selection-drawer-head">
        <div>
          <h2 id="selectionDrawerTitle">已选志愿清单</h2>
          <div class="mini" id="selectionDrawerSub">按志愿顺序展示，可调整顺序与拖拽左边缘改变宽度。</div>
        </div>
        <div class="selection-drawer-head-actions">
          <button type="button" class="secondary-button primary-action" id="pinSelectionCart">固定侧栏</button>
          <button type="button" class="secondary-button" id="closeSelectionDrawer">关闭</button>
        </div>
      </div>
      <div class="drawer-count-grid">
        <div class="drawer-count challenge"><span>冲</span><b id="drawerChallengeCount">0</b></div>
        <div class="drawer-count steady"><span>稳</span><b id="drawerSteadyCount">0</b></div>
        <div class="drawer-count safe"><span>保</span><b id="drawerSafeCount">0</b></div>
      </div>
      <div class="selection-drawer-body" id="selectionDrawerGroups"></div>
      <div class="selection-drawer-footer">
        <button type="button" class="secondary-button danger-text-button" id="drawerClearSelected">清空</button>
        <button type="button" id="drawerCloseFooter">完成</button>
      </div>
    </div>

    <button type="button" class="cart-dock-button" id="cartDockButton"><span>已选清单</span><b id="cartDockCount">0</b></button>

    <footer class="footer">Powered by Gao（Gavin）</footer>
  </div>
  <div class="tooltip-layer" id="tooltipLayer" role="tooltip"></div>

  <script>
    const form = document.getElementById('form');
    const riskOrder = ['高冲', '冲', '稳中偏冲', '稳', '保', '强保', '证据不足'];
    const PAGE_SIZE_OPTIONS = [10, 20, 30];
    const APP_VERSION = 'V1.0 版本';
    const strategyLabels = { aggressive: '激进预设', balanced: '均衡预设', conservative: '保守预设', custom: '自定义' };
    const strategyCompareOrder = ['conservative', 'balanced', 'aggressive', 'custom'];
    const strategyBaseQuotas = {
      conservative: { '高冲': 0, '冲': 8, '稳中偏冲': 18, '稳': 35, '保': 25, '强保': 10 },
      balanced: { '高冲': 2, '冲': 16, '稳中偏冲': 24, '稳': 30, '保': 19, '强保': 5 },
      aggressive: { '高冲': 8, '冲': 22, '稳中偏冲': 24, '稳': 24, '保': 14, '强保': 4 },
    };
    const strategyGapSettings = {
      conservative: { challenge: '-8~0分', steady: '0~15分', safe: '15分以上' },
      balanced: { challenge: '-12~0分', steady: '0~12分', safe: '12分以上' },
      aggressive: { challenge: '-18~0分', steady: '0~10分', safe: '10分以上' },
    };
    const strategyDescriptions = {
      conservative: '当前使用保守预设：稳、保占比更高，适合优先降低滑档风险。',
      balanced: '当前使用均衡预设：冲、稳、保比例相对均衡，适合作为默认参考方案。',
      aggressive: '当前使用激进预设：冲刺项更多，适合愿意承担更高不确定性的方案。',
      custom: '当前使用自定义方案：可直接在卡片内修改冲、稳、保的分差说明和志愿数量。'
    };
    const customQuotaFields = [
      { band: '高冲', name: 'customQuotaHighChallenge' },
      { band: '冲', name: 'customQuotaChallenge' },
      { band: '稳中偏冲', name: 'customQuotaLeanSteady' },
      { band: '稳', name: 'customQuotaSteady' },
      { band: '保', name: 'customQuotaSafe' },
      { band: '强保', name: 'customQuotaStrongSafe' },
    ];
    const subjectOptions = ['物理', '化学', '生物', '地理', '历史', '思想政治'];
    let selectedSubjects = ['物理', '化学', '生物'];
    const interestOptions = [
      { group: '计算机与电子信息', items: ['计算机', '软件', '人工智能', '数据科学', '网络空间安全', '信息安全', '电子', '电子信息', '通信工程', '集成电路', '微电子', '物联网', '智能科学', '自动化', '机器人工程', '仪器测控'] },
      { group: '工程制造与能源', items: ['机械', '电气', '车辆工程', '航空航天', '航空飞行', '船舶', '兵器', '土木', '建筑环境', '交通', '能源', '新能源', '材料', '冶金', '测绘', '矿业资源', '水利', '环境工程', '安全工程'] },
      { group: '数学自然科学', items: ['数学', '统计', '物理', '应用物理', '化学', '应用化学', '生物科学', '地理科学', '大气科学', '海洋科学', '地质学', '生态学', '心理学'] },
      { group: '医学与健康', items: ['医学', '临床医学', '口腔医学', '基础医学', '预防医学', '中医学', '中医药细分', '药学', '医学影像', '医学检验', '护理学', '康复治疗', '生物医学工程'] },
      { group: '财经管理', items: ['金融', '经济学', '财政学', '税收学', '会计学', '财务管理', '审计学', '工商管理', '市场营销', '人力资源', '物流管理', '会展传播', '采购零售', '信息管理与信息系统', '数据管理', '电子商务', '国际经济与贸易'] },
      { group: '法政公共与社会', items: ['法学', '知识产权', '政治学', '思想政治教育', '社会学', '社会工作', '公共管理', '行政管理', '公安学', '马克思主义理论'] },
      { group: '教育语言与传媒', items: ['师范', '教育学', '学前教育', '小学教育', '汉语言文学', '外国语言文学', '英语', '小语种', '新闻传播', '广告学', '网络与新媒体', '编辑出版', '播音主持'] },
      { group: '设计建筑艺术与体育', items: ['设计', '工业设计', '数字媒体', '动画', '美术学', '音乐学', '戏剧影视', '建筑学', '城乡规划', '风景园林', '服装设计', '体育运动'] },
      { group: '农林食品与生命产业', items: ['农学', '植物保护', '园艺', '动物医学', '动物科学', '林学', '水产', '食品科学', '食品质量', '食品酿造', '草业科学'] },
      { group: '文史哲与档案', items: ['历史学', '考古学', '文化遗产', '哲学', '档案学', '图书情报', '文化产业管理', '旅游管理', '酒店管理'] },
    ];
    let interestAnswers = {};
    let generatedInterestKeywords = [];
    let selectedInterests = [];
    let settingsDirty = false;
    let systemRecommendations = [];
    let currentRecommendations = [];
    let candidateRecommendations = [];
    let searchRecommendations = [];
    let majorCatalog = [];
    let admissionMajorCatalog = [];
    let majorSelectionCache = [];
    let selectedMajors = [];
    let recommendedMajorNames = [];
    let selectedOptionKeys = new Set();
    let selectedOptionOrder = [];
    let candidateSearchText = '';
    let candidateRiskFilter = 'all';
    let freeSelectionMode = false;
    let matchedPage = 1;
    let recommendationPage = 1;
    let pageSize = PAGE_SIZE_OPTIONS[0];
    let planOrderDirty = true;
    let latestPlanData = null;
    let customGapNumbers = { challenge: 12, steady: 12, safe: 12 };
    let appStarted = false;
    let systemInfo = null;
    let startupComplianceShown = false;
    let activeInfoDialogKind = '';
    let startupAgreementRequired = false;
    let startupReadyPromise = null;
    let dataSourceState = null;
    let dataSourceEditTarget = null;
    let dataSourceSelectedYear = '';
    let dataSourceManagerInitialized = false;
    let dataSourceActiveTab = 'sources';
    let dataRecordSelection = null;
    let dataRecordPage = 1;
    let dataRecordPayload = null;
    let activeSettingsPanel = 'strategy';
    let selectionCartPinned = false;
    let selectionDrawerWidth = 840;
    let drawerResizeState = null;
    let selectedCartItemsCache = null;
    let reportHtmlCache = { signature: '', html: '' };
    let draggedRecommendationIndex = null;
    let pointerDragState = null;
    const schoolMetaMap = {
      '清华大学': ['北京', ['985', '211', '双一流']],
      '北京大学': ['北京', ['985', '211', '双一流']],
      '中国人民大学': ['北京', ['985', '211', '双一流']],
      '北京航空航天大学': ['北京', ['985', '211', '双一流']],
      '北京理工大学': ['北京', ['985', '211', '双一流']],
      '北京师范大学': ['北京', ['985', '211', '双一流']],
      '中国农业大学': ['北京', ['985', '211', '双一流']],
      '中央民族大学': ['北京', ['985', '211', '双一流']],
      '复旦大学': ['上海', ['985', '211', '双一流']],
      '上海交通大学': ['上海', ['985', '211', '双一流']],
      '同济大学': ['上海', ['985', '211', '双一流']],
      '华东师范大学': ['上海', ['985', '211', '双一流']],
      '浙江大学': ['浙江 杭州', ['985', '211', '双一流']],
      '南京大学': ['江苏 南京', ['985', '211', '双一流']],
      '东南大学': ['江苏 南京', ['985', '211', '双一流']],
      '中国科学技术大学': ['安徽 合肥', ['985', '211', '双一流']],
      '哈尔滨工业大学': ['黑龙江 哈尔滨', ['985', '211', '双一流']],
      '哈尔滨工业大学(威海)': ['山东 威海', ['985', '211', '双一流']],
      '哈尔滨工业大学(深圳)': ['广东 深圳', ['985', '211', '双一流']],
      '西安交通大学': ['陕西 西安', ['985', '211', '双一流']],
      '西北工业大学': ['陕西 西安', ['985', '211', '双一流']],
      '武汉大学': ['湖北 武汉', ['985', '211', '双一流']],
      '华中科技大学': ['湖北 武汉', ['985', '211', '双一流']],
      '中山大学': ['广东 广州', ['985', '211', '双一流']],
      '华南理工大学': ['广东 广州', ['985', '211', '双一流']],
      '四川大学': ['四川 成都', ['985', '211', '双一流']],
      '电子科技大学': ['四川 成都', ['985', '211', '双一流']],
      '重庆大学': ['重庆', ['985', '211', '双一流']],
      '天津大学': ['天津', ['985', '211', '双一流']],
      '南开大学': ['天津', ['985', '211', '双一流']],
      '厦门大学': ['福建 厦门', ['985', '211', '双一流']],
      '山东大学': ['山东 济南', ['985', '211', '双一流']],
      '中国海洋大学': ['山东 青岛', ['985', '211', '双一流']],
      '中国石油大学(华东)': ['山东 青岛', ['211', '双一流']],
      '北京邮电大学': ['北京', ['211', '双一流']],
      '西安电子科技大学': ['陕西 西安', ['211', '双一流']],
      '南京航空航天大学': ['江苏 南京', ['211', '双一流']],
      '南京理工大学': ['江苏 南京', ['211', '双一流']],
      '苏州大学': ['江苏 苏州', ['211', '双一流']],
      '上海财经大学': ['上海', ['211', '双一流']],
      '中央财经大学': ['北京', ['211', '双一流']],
      '对外经济贸易大学': ['北京', ['211', '双一流']],
      '北京交通大学': ['北京', ['211', '双一流']],
      '北京科技大学': ['北京', ['211', '双一流']],
      '华北电力大学': ['北京', ['211', '双一流']],
      '南京师范大学': ['江苏 南京', ['211', '双一流']],
      '华东理工大学': ['上海', ['211', '双一流']],
      '东华大学': ['上海', ['211', '双一流']],
      '上海大学': ['上海', ['211', '双一流']],
      '郑州大学': ['河南 郑州', ['211', '双一流']],
      '合肥工业大学': ['安徽 合肥', ['211', '双一流']],
      '福州大学': ['福建 福州', ['211', '双一流']],
      '南昌大学': ['江西 南昌', ['211', '双一流']],
      '湖南大学': ['湖南 长沙', ['985', '211', '双一流']],
      '中南大学': ['湖南 长沙', ['985', '211', '双一流']],
      '吉林大学': ['吉林 长春', ['985', '211', '双一流']],
      '东北大学': ['辽宁 沈阳', ['985', '211', '双一流']],
      '大连理工大学': ['辽宁 大连', ['985', '211', '双一流']],
      '兰州大学': ['甘肃 兰州', ['985', '211', '双一流']],
      '西北农林科技大学': ['陕西 杨凌', ['985', '211', '双一流']],
    };
    const interestQuestions = [
      { id: 'R1', type: 'R', text: '如果要解决一个真实问题，我更愿意先拆开设备、搭模型、做实验，而不是只讨论概念。' },
      { id: 'R2', type: 'R', text: '看到机械、电路、建筑、交通、能源系统的工作原理，我会自然想知道它怎么运转。' },
      { id: 'R3', type: 'R', text: '相比长时间写作或演讲，我更能接受需要动手、调试、测量、反复改进的任务。' },
      { id: 'R4', type: 'R', text: '我希望大学专业能让我接触设备、工程现场、制造流程或实际系统。' },
      { id: 'I1', type: 'I', text: '遇到复杂问题时，我会想查资料、建假设、推导原因，而不急着得到一个简单答案。' },
      { id: 'I2', type: 'I', text: '数学、算法、自然科学、医学原理或数据规律中，至少有一类能让我持续钻研。' },
      { id: 'I3', type: 'I', text: '我愿意为了弄清一个问题，忍受较长时间的抽象学习、实验失败或数据清洗。' },
      { id: 'I4', type: 'I', text: '相比重复执行流程，我更希望专业训练我分析未知问题和提出解释。' },
      { id: 'A1', type: 'A', text: '我会关注表达效果、审美、文字、影像、空间或产品体验，而不只关注功能是否可用。' },
      { id: 'A2', type: 'A', text: '如果作业允许开放表达，我通常会想做出有个人风格或新鲜角度的作品。' },
      { id: 'A3', type: 'A', text: '我愿意长期打磨写作、设计、传播、建筑空间、数字媒体或内容创作能力。' },
      { id: 'A4', type: 'A', text: '我不太喜欢所有任务都有唯一标准答案，更喜欢有创作空间的任务。' },
      { id: 'S1', type: 'S', text: '我愿意花时间理解一个人的困难，并帮助他学习、康复、沟通或做决定。' },
      { id: 'S2', type: 'S', text: '相比独自完成技术任务，我也能从教学、咨询、医疗、公共服务中获得成就感。' },
      { id: 'S3', type: 'S', text: '当别人因为我的解释或帮助而变好时，我会觉得这件事有意义。' },
      { id: 'S4', type: 'S', text: '我能接受未来工作需要较多沟通、耐心、责任感和情绪稳定。' },
      { id: 'E1', type: 'E', text: '我愿意主动组织别人、推动项目、谈判资源或承担结果压力。' },
      { id: 'E2', type: 'E', text: '商业、金融、法律、管理、政策、市场竞争这类议题会让我有兴趣。' },
      { id: 'E3', type: 'E', text: '如果一个方案需要公开表达、说服别人或承担风险，我并不排斥。' },
      { id: 'E4', type: 'E', text: '我希望专业能连接组织决策、商业价值、制度规则或社会影响力。' },
      { id: 'C1', type: 'C', text: '我擅长把信息整理成清楚的表格、流程、账目、清单或规范文档。' },
      { id: 'C2', type: 'C', text: '相比高度开放的任务，我更喜欢规则明确、标准清楚、能稳定提高准确率的任务。' },
      { id: 'C3', type: 'C', text: '我能接受会计、审计、统计、档案、数据治理、运营管理这类细致工作。' },
      { id: 'C4', type: 'C', text: '我重视稳定性、秩序、合规和可靠交付，不喜欢长期处在混乱试错中。' },
    ];
    const interestTypeLabels = {
      R: '现实工程型',
      I: '研究分析型',
      A: '艺术表达型',
      S: '社会服务型',
      E: '经营管理型',
      C: '事务规范型',
    };
    const interestKeywordMap = {
      R: ['机械', '电气', '自动化', '土木', '交通', '能源', '材料', '仪器测控', '矿业资源', '航空飞行'],
      I: ['计算机', '软件', '人工智能', '数据科学', '数学', '统计', '物理', '化学', '生物科学', '医学', '文化遗产'],
      A: ['设计', '建筑学', '数字媒体', '新闻传播', '汉语言文学', '广告学', '小语种', '文化遗产', '会展传播'],
      S: ['师范', '教育学', '心理学', '临床医学', '口腔医学', '护理学', '社会工作', '中医药细分', '体育运动'],
      E: ['金融', '经济学', '法学', '工商管理', '市场营销', '国际经济与贸易', '会展传播', '采购零售'],
      C: ['会计学', '财务管理', '审计学', '信息管理与信息系统', '数据管理', '档案学', '采购零售', '仪器测控'],
    };
    const majorInterestAliases = {
      计算机: ['计算机', '软件', '人工智能', '数据科学', '网络空间安全', '信息安全', '智能科学', '物联网', '区块链', '密码科学', '数字媒体技术'],
      软件: ['软件', '计算机', '人工智能', '数据科学', '网络空间安全'],
      人工智能: ['人工智能', '智能科学', '机器人工程', '具身智能', '脑机科学', '自动化', '计算机'],
      医学: ['临床医学', '口腔医学', '基础医学', '麻醉学', '医学影像学', '眼视光医学', '精神医学', '儿科学', '预防医学', '中医学', '药学', '医学检验技术', '护理学', '智能医学工程', '医工学'],
      临床医学: ['临床医学', '麻醉学', '医学影像学', '眼视光医学', '精神医学', '儿科学'],
      口腔医学: ['口腔医学'],
      基础医学: ['基础医学', '生物医学科学', '生物医学'],
      药学: ['药学', '临床药学', '药物制剂', '中药学'],
      电子: ['电子', '电子信息', '通信工程', '集成电路', '微电子', '光电信息'],
      自动化: ['自动化', '机器人工程', '智能装备', '智能制造', '测控技术'],
      仪器测控: ['测控技术与仪器', '仪器', '精密仪器', '智能感知', '光电信息', '传感器'],
      航空飞行: ['飞行技术', '飞行器', '航空航天', '无人驾驶航空器', '智慧民航', '低空技术', '空中交通'],
      矿业资源: ['采矿', '矿物', '矿业', '资源勘查', '勘查技术', '地质工程', '石油工程', '油气储运'],
      金融: ['金融', '经济', '精算', '投资', '保险', '财政', '税收'],
      法学: ['法学', '知识产权', '纪检监察', '司法', '公安', '国家安全'],
      师范: ['教育', '师范', '学前教育', '小学教育', '特殊教育'],
      小语种: ['俄语', '日语', '德语', '法语', '西班牙语', '阿拉伯语', '朝鲜语', '葡萄牙语', '意大利语', '泰语', '越南语', '外国语言文学', '翻译'],
      机械: ['机械', '智能制造', '车辆工程', '机器人工程'],
      电气: ['电气', '能源', '新能源', '储能'],
      设计: ['设计', '数字媒体', '动画', '美术', '艺术'],
      体育运动: ['体育教育', '运动训练', '社会体育指导与管理', '运动人体科学', '运动康复', '休闲体育', '体能训练', '体育经济'],
      食品酿造: ['酿酒工程', '葡萄与葡萄酒工程', '食品科学与工程', '食品质量与安全', '食品营养', '粮食工程', '乳品工程'],
      中医药细分: ['中医学', '中药学', '针灸推拿学', '中医养生学', '中医康复学', '中医骨伤科学', '中草药栽培', '中药制药'],
      文化遗产: ['文物与博物馆学', '文物保护', '文化遗产', '非物质文化遗产保护', '考古学', '历史建筑保护'],
      会展传播: ['会展经济与管理', '会展', '传播学', '新闻学', '广播电视学', '网络与新媒体', '广告学', '编辑出版'],
      采购零售: ['采购管理', '零售业管理', '供应链管理', '物流管理', '电子商务', '市场营销'],
    };
    const selectedMajorAliasMap = {
      '计算机科学与技术': ['计算机科学与技术', '计算机'],
      '软件工程': ['软件工程', '软件'],
      '人工智能': ['人工智能'],
      '数据科学与大数据技术': ['数据科学与大数据技术', '数据科学', '大数据'],
      '网络空间安全': ['网络空间安全'],
      '信息安全': ['信息安全'],
      '电子信息工程': ['电子信息工程', '电子信息'],
      '电子科学与技术': ['电子科学与技术', '电子'],
      '通信工程': ['通信工程', '通信'],
      '集成电路设计与集成系统': ['集成电路设计与集成系统', '集成电路'],
      '自动化': ['自动化'],
      '机器人工程': ['机器人工程', '机器人'],
      '临床医学': ['临床医学'],
      '口腔医学': ['口腔医学'],
      '基础医学': ['基础医学'],
      '麻醉学': ['麻醉学'],
      '医学影像学': ['医学影像学'],
      '医学检验技术': ['医学检验技术'],
      '护理学': ['护理学'],
      '法学': ['法学'],
      '会计学': ['会计学'],
      '金融学': ['金融学'],
    };
    let progressTimer = null;
    let progressValue = 0;
    let progressStartedAt = 0;

    function fmt(value) {
      if (value === null || value === undefined || value === '') return '待接入';
      return String(Math.round(Number(value))).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }
    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      }[char]));
    }
    function helpIcon(text) {
      const safe = escapeHtml(text);
      return `<span class="help-icon" tabindex="0" role="img" aria-label="${safe}" title="${safe}" data-tooltip="${safe}">?</span>`;
    }
    function calcValue(value, helpText, extraClass = '') {
      return `<span class="calc-value ${extraClass}">${value}${helpIcon(helpText)}</span>`;
    }
    function setupHelpTooltips() {
      const layer = document.getElementById('tooltipLayer');
      if (!layer) return;
      let activeTarget = null;
      let pinnedTooltip = false;
      const tooltipSelector = '.help-icon, .tooltip-trigger';
      function tooltipTarget(event) {
        const target = event.target;
        return target && target.closest ? target.closest(tooltipSelector) : null;
      }
      function positionLayer(target) {
        if (!target || !layer.classList.contains('open')) return;
        const rect = target.getBoundingClientRect();
        const layerRect = layer.getBoundingClientRect();
        const margin = 12;
        const gap = 10;
        let left = rect.left + rect.width / 2 - layerRect.width / 2;
        left = Math.max(margin, Math.min(left, window.innerWidth - layerRect.width - margin));
        const top = Math.max(margin, rect.top - layerRect.height - gap);
        layer.style.left = `${Math.round(left)}px`;
        layer.style.top = `${Math.round(top)}px`;
      }
      function showTooltip(target, pinned = false) {
        const text = target && target.getAttribute('data-tooltip');
        if (!text) return;
        activeTarget = target;
        pinnedTooltip = pinned;
        if (target.hasAttribute('title')) {
          target.dataset.savedTitle = target.getAttribute('title') || '';
          target.removeAttribute('title');
        }
        layer.textContent = text;
        layer.classList.add('open');
        positionLayer(target);
      }
      function hideTooltip(target, force = false) {
        if (pinnedTooltip && !force) return;
        if (target && activeTarget && target !== activeTarget) return;
        layer.classList.remove('open');
        activeTarget = null;
        pinnedTooltip = false;
      }
      document.addEventListener('mouseover', event => {
        const target = tooltipTarget(event);
        if (target && target !== activeTarget) showTooltip(target);
      });
      document.addEventListener('mousemove', event => {
        const target = tooltipTarget(event);
        if (target && target !== activeTarget && !pinnedTooltip) showTooltip(target);
      });
      document.addEventListener('focusin', event => {
        const target = tooltipTarget(event);
        if (target) showTooltip(target);
      });
      document.addEventListener('mouseout', event => {
        const target = tooltipTarget(event);
        if (target && !target.contains(event.relatedTarget)) hideTooltip(target);
      });
      document.addEventListener('focusout', event => {
        const target = tooltipTarget(event);
        if (target) hideTooltip(target);
      });
      document.addEventListener('click', event => {
        const target = tooltipTarget(event);
        if (!target) {
          hideTooltip(null, true);
          return;
        }
        if (target === activeTarget && pinnedTooltip) {
          hideTooltip(target, true);
          return;
        }
        showTooltip(target, true);
      });
      window.addEventListener('resize', () => positionLayer(activeTarget));
      document.addEventListener('scroll', () => positionLayer(activeTarget), true);
    }
    function percent(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return '待接入';
      return `${Math.round(Number(value))}%`;
    }
    function scopedStorageKey(baseKey) {
      return baseKey;
    }
    function officialItemFound(status, key) {
      return Boolean(status && status.items && status.items[key] && status.items[key].found);
    }
    function formatCheckedAt(value) {
      if (!value) return '未记录时间';
      const compact = String(value).replace(/([+-]\d{2})(\d{2})$/, '$1:$2');
      const date = new Date(compact);
      if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
      return date.toLocaleString('zh-CN', { hour12: false });
    }
    function refreshSystemInfoUI() {
      const target = document.getElementById('latestDataUpdatedAt');
      if (!target) return;
      const status = systemInfo && systemInfo.official_2026_status ? systemInfo.official_2026_status : null;
      const checkedAt = status && status.checked_at ? formatCheckedAt(status.checked_at) : '';
      target.textContent = `最新数据更新时间：${checkedAt || '待核验'}`;
    }
    async function loadSystemInfo() {
      try {
        const response = await fetch('/api/system-info');
        if (!response.ok) throw new Error(await response.text());
        systemInfo = await response.json();
        refreshSystemInfoUI();
      } catch (error) {
        systemInfo = {};
        refreshSystemInfoUI();
      }
    }
    function startApp() {
      if (appStarted) return;
      appStarted = true;
      window.requestAnimationFrame(() => {
        loadMajorCatalog().catch(error => {
          console.warn(error);
        });
        const initialRank = String(form.elements.rank.value || '').trim();
        if (/^[1-9]\d*$/.test(initialRank)) {
          window.setTimeout(() => {
            loadPlan(false).catch(error => alert(error.message));
          }, 80);
        } else {
          setActiveStep('2');
        }
      });
    }
    function showStartupCompliance() {
      if (startupComplianceShown) return;
      startupComplianceShown = true;
      window.requestAnimationFrame(() => openInfoDialog('compliance', { requireAgreement: true }));
    }
    function splitTerms(value) {
      return value.split(/[,\s，、;；/]+/).map(x => x.trim()).filter(Boolean);
    }
    function profileFilterSummaryText() {
      const parts = [];
      const priorityLabels = {
        balanced: '均衡',
        school: '院校层次优先',
        major: '专业匹配优先',
        city: '城市优先',
        cost: '成本优先',
      };
      const priority = form.elements.priority ? form.elements.priority.value : 'balanced';
      if (priority && priority !== 'balanced') parts.push(priorityLabels[priority] || priority);
      const bandWidth = String(form.elements.bandWidth ? form.elements.bandWidth.value : '').trim();
      if (bandWidth && bandWidth !== '20') parts.push(`浮动${bandWidth}分`);
      const maxTuition = String(form.elements.maxTuition ? form.elements.maxTuition.value : '').trim();
      if (maxTuition) parts.push(`学费≤${maxTuition}`);
      const preferredCities = splitTerms(form.elements.preferredCities ? form.elements.preferredCities.value : '').slice(0, 2);
      if (preferredCities.length) parts.push(`偏好${preferredCities.join('、')}`);
      const blockedCities = splitTerms(form.elements.blockedCities ? form.elements.blockedCities.value : '').slice(0, 2);
      if (blockedCities.length) parts.push(`排除${blockedCities.join('、')}`);
      const avoidKeywords = splitTerms(form.elements.avoidKeywords ? form.elements.avoidKeywords.value : '').slice(0, 2);
      if (avoidKeywords.length) parts.push(`避开${avoidKeywords.join('、')}`);
      const checkedRules = [
        ['requirePublicUndergrad', '公办'],
        ['requireDoubleFirstClass', '双一流'],
        ['require985', '985'],
        ['require211', '211'],
        ['allowPrivate', '民办'],
        ['allowSinoForeign', '中外合作'],
      ].filter(([name]) => form.elements[name] && form.elements[name].checked).map(([, label]) => label);
      if (checkedRules.length) parts.push(checkedRules.slice(0, 3).join('、'));
      return parts.length ? parts.slice(0, 4).join(' · ') : '默认筛选';
    }
    function syncProfileFilterSummary() {
      const summary = document.getElementById('filterSummaryNote');
      const text = profileFilterSummaryText();
      if (summary) summary.textContent = text;
      const slideSummary = document.getElementById('settingsSlideSummary');
      if (slideSummary && activeSettingsPanel === 'profile') slideSummary.textContent = text;
    }
    function riskClass(name) {
      return 'risk-' + name;
    }
    function optionSchool(item) {
      return String(item.option_name || '').split(' / ')[0] || '未知院校';
    }
    function optionMajor(item) {
      return String(item.option_name || '').split(' / ').slice(1).join(' / ') || '未知专业';
    }
    function optionCodes(item) {
      const debug = item.debug || {};
      const identity = debug.identity || {};
      const raw = String(item.option_key || '');
      const [schoolCode, majorCode] = raw.split(':');
      return {
        schoolCode: identity.school_code || debug.school_code || schoolCode || '待核对',
        majorCode: identity.major_code || debug.major_code || majorCode || '待核对',
      };
    }
    function schoolMeta(item) {
      const school = optionSchool(item);
      const debug = item.debug || {};
      const mapped = schoolMetaMap[school] || ['', []];
      const city = debug.city || mapped[0] || '待核对';
      const rawTags = new Set([...(mapped[1] || []), ...(debug.tags || [])]);
      if (debug.school_type) rawTags.add(debug.school_type);
      const tags = Array.from(rawTags).filter(Boolean);
      return { school, city, tags };
    }
    function isSchoolLevelTag(tag) {
      return ['985', '211', '双一流'].includes(String(tag || '').trim());
    }
    function schoolLevelTags(item) {
      return (schoolMeta(item).tags || []).filter(isSchoolLevelTag);
    }
    function optionProjectTags(item) {
      const tags = schoolMeta(item).tags || [];
      return Array.from(new Set(tags.filter(tag => tag && !isSchoolLevelTag(tag) && tag !== '本科')));
    }
    function latestEvidence(item, year = 2025) {
      const evidence = item.evidence || [];
      return evidence.find(e => e.year === year) || evidence[evidence.length - 1] || {};
    }
    function evidenceQuality(item) {
      const debug = item.debug || {};
      const quality = debug.evidence_quality || {};
      const years = quality.valid_years || (item.evidence || []).filter(e => e.min_rank !== null && e.min_rank !== undefined).length;
      if (years >= 3) return { label: '三年证据', cls: 'strong', text: '证据较充分' };
      if (years === 2) return { label: '两年证据', cls: 'medium', text: '可参考，需看趋势' };
      if (years === 1) return { label: '单年样本', cls: 'weak', text: '证据不足，不能单独作为排序依据' };
      return { label: '无有效位次', cls: 'weak', text: '只能作为人工候选' };
    }
    function optionIdentity(item) {
      const debug = item.debug || {};
      const identity = debug.identity || {};
      const parts = [
        identity.option_code ? `代码 ${identity.option_code}` : item.option_key,
        identity.school_type ? `类型 ${identity.school_type}` : '',
        identity.campus ? `校区 ${identity.campus}` : '',
        identity.tuition ? `学费 ${fmt(identity.tuition)}` : '',
        identity.subjects && identity.subjects.length ? `选科 ${identity.subjects.join('/')}` : '',
      ].filter(Boolean);
      return parts.join(' · ');
    }
    function majorKnowledgeText(item) {
      const knowledge = item.debug && item.debug.major_knowledge;
      if (knowledge && knowledge.length) return knowledge.join('；');
      return '未发现特殊提醒；填报前仍要看培养方案、就业方向和转专业规则。';
    }
    function shortText(value, limit = 58) {
      const text = String(value || '').replace(/\s+/g, ' ').trim();
      return text.length > limit ? `${text.slice(0, limit)}...` : text;
    }
    function charterInfo(item) {
      const debug = item.debug || {};
      return debug.charter_2026 || {};
    }
    function charterStatusClass(info) {
      if ((info.rules || []).length) return 'alert';
      return info.status === 'verified' ? 'verified' : 'pending';
    }
    function charterStatusText(info) {
      if ((info.rules || []).length) return `章程风险 ${info.rules.length}项`;
      if (info.status === 'verified') return '章程已核验';
      return '章程待核验';
    }
    function charterLinkHtml(info) {
      const url = info.source_url || info.official_school_url || '';
      if (!url) return '';
      const title = info.source_title || '2026 招生章程';
      return `<a class="charter-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(title)}">查看简章</a>`;
    }
    function charterActionLinkHtml(item) {
      const link = charterLinkHtml(charterInfo(item));
      return link || '<span class="charter-link disabled">无简章</span>';
    }
    function plainCharterRuleText(rule) {
      const text = String(rule.summary || rule.evidence || '');
      const category = String(rule.category || '');
      if (category.includes('身体') || /体检|色盲|色弱|视力|嗅觉|身高|身体复查/.test(text)) {
        if (/色盲|色弱|色觉/.test(text)) return '可能有色盲、色弱或色觉限制';
        if (/视力|身高|嗅觉/.test(text)) return '可能有视力、身高或嗅觉要求';
        return '需要核对体检和身体条件';
      }
      if (category.includes('单科') || category.includes('语种') || /单科|外语|英语|口语|语种/.test(text)) {
        if (/英语授课|非英语|外语教学/.test(text)) return '非英语语种考生要谨慎';
        if (/单科|成绩/.test(text)) return '可能有单科成绩或同分排序要求';
        return '需要核对外语语种要求';
      }
      if (category.includes('地域') || category.includes('校区') || /校区|办学地点|培养地点|就读地点|地址/.test(text)) {
        return '需要核对校区和就读地点';
      }
      if (category.includes('政治') || /政审|政治面貌|思想品德/.test(text)) {
        return '需要核对政审或思想品德要求';
      }
      return shortText(text, 36) || '需要打开章程核对';
    }
    function charterRuleGroupKey(rule) {
      const text = String(rule.summary || rule.evidence || '');
      const category = String(rule.category || '');
      if (category.includes('身体') || /体检|色盲|色弱|色觉|视力|嗅觉|身高|身体复查/.test(text)) return 'body';
      if (category.includes('单科') || category.includes('语种') || /单科|外语|英语|口语|语种|同分/.test(text)) return 'score';
      if (category.includes('地域') || category.includes('校区') || /校区|办学地点|培养地点|就读地点|地址/.test(text)) return 'campus';
      if (category.includes('政治') || /政审|政治面貌|思想品德/.test(text)) return 'politics';
      return category || 'other';
    }
    function mergedCharterRuleText(key, rules) {
      const text = rules.map(rule => String(rule.summary || rule.evidence || '')).join('；');
      if (key === 'body') {
        return '该专业有身体条件要求，请注意核对招生简章';
      }
      if (key === 'score') {
        const hasLanguage = /外语|英语|口语|语种|英语授课|非英语/.test(text);
        const hasScore = /单科|成绩|同分|语文|数学/.test(text);
        if (hasLanguage && hasScore) return '需核对语种、单科或同分规则';
        if (hasLanguage) return '需核对外语语种或授课语言';
        return '需核对单科成绩或同分规则';
      }
      if (key === 'campus') return '需核对校区和就读地点';
      if (key === 'politics') return '需核对政审或思想品德要求';
      return plainCharterRuleText(rules[0] || {});
    }
    function charterRuleGroupLabel(key, fallback) {
      if (key === 'body') return '身体条件';
      if (key === 'score') return '单科/语种';
      if (key === 'campus') return '校区地点';
      if (key === 'politics') return '政审/政治';
      return fallback || '章程';
    }
    function compactCharterRules(rules) {
      const groups = [];
      const index = new Map();
      (rules || []).forEach(rule => {
        const key = charterRuleGroupKey(rule);
        if (!index.has(key)) {
          index.set(key, { key, category: rule.category || '章程', rules: [] });
          groups.push(index.get(key));
        }
        index.get(key).rules.push(rule);
      });
      return groups.map(group => ({
        category: charterRuleGroupLabel(group.key, group.category),
        text: mergedCharterRuleText(group.key, group.rules),
        title: group.rules.map(rule => rule.summary || rule.evidence || '').filter(Boolean).join('；'),
      }));
    }
    function charterTooltipText(info, limit = 5) {
      const rules = compactCharterRules(info.rules || []).slice(0, limit);
      if (rules.length) {
        const rows = rules.map((rule, index) => {
          const title = rule.title ? `\n原文摘要：${shortText(rule.title, 150)}` : '';
          return `${index + 1}. ${rule.category || '章程'}：${rule.text}${title}`;
        });
        const more = (info.rules || []).length > limit ? `\n另有 ${(info.rules || []).length - limit} 项，请打开原文核对。` : '';
        return `招生章程风险详情\n${rows.join('\n')}${more}\n正式填报前必须打开招生简章原文逐条核对。`;
      }
      if (info.status === 'verified') {
        return `章程已核验\n${info.summary || '未抽到政治面貌、身体条件、单科分数、地域/校区四类明确限制；仍需看原文。'}`;
      }
      return `章程待核验\n${info.summary || '该校 2026 官方章程仍需打开来源核验。'}`;
    }
    function charterStatusBadgeHtml(info, limit = 5) {
      const tooltip = escapeHtml(charterTooltipText(info, Math.max(5, limit)));
      const label = escapeHtml(charterStatusText(info));
      return `<span class="charter-status ${charterStatusClass(info)} tooltip-trigger" tabindex="0" role="button" aria-label="${tooltip}" data-tooltip="${tooltip}">${label}</span>`;
    }
    function charterCompactHtml(item, limit = 3) {
      const info = charterInfo(item);
      return `<span class="charter-inline">
        <span class="charter-topline">
          ${charterStatusBadgeHtml(info, limit)}
        </span>
      </span>`;
    }
    function charterReportText(item) {
      const info = charterInfo(item);
      const rules = (info.rules || []).map(rule => `${rule.category}：${rule.summary}`).join('；');
      if (rules) return `${charterStatusText(info)}；${rules}`;
      return `${charterStatusText(info)}；${info.summary || '需打开官方原文核验'}`;
    }
    function splitRecommendationReasons(item) {
      const reasons = item.reasons || [];
      const interests = [];
      const related = [];
      const other = [];
      reasons.forEach(reason => {
        const text = String(reason || '');
        if (text.startsWith('匹配专业：')) interests.push(text.replace('匹配专业：', ''));
        else if (text.startsWith('相关专业族：')) related.push(text.replace('相关专业族：', ''));
        else other.push(text);
      });
      return { interests, related, other };
    }
    function compactTagHtml(items, fallback) {
      const values = Array.from(new Set((items || []).filter(Boolean)));
      if (!values.length) return `<span class="compact-note">${fallback}</span>`;
      return `<span class="compact-tags">${values.map(item => `<span class="compact-tag">${escapeHtml(item)}</span>`).join('')}</span>`;
    }
    function sortActionHtml(item, globalIndex) {
      return `<div class="sort-card-actions">
        <div class="sort-move-row">
          <button type="button" title="上移" aria-label="上移" data-action="up" data-index="${globalIndex}">上移</button>
          <button type="button" title="下移" aria-label="下移" data-action="down" data-index="${globalIndex}">下移</button>
          <span class="move-to-control" title="移到指定序号">移至
            <input type="number" min="1" max="${currentRecommendations.length}" inputmode="numeric" data-move-target data-index="${globalIndex}">
            <button type="button" data-action="move-to" data-index="${globalIndex}">确定</button>
          </span>
        </div>
        <div class="sort-secondary-row">
          ${charterActionLinkHtml(item)}
          <button type="button" class="${item.locked ? 'active' : ''}" title="${item.locked ? '解锁' : '锁定'}" aria-label="${item.locked ? '解锁' : '锁定'}" data-action="lock" data-index="${globalIndex}">${item.locked ? '解锁' : '锁定'}</button>
          <button type="button" class="delete-button" title="删除" aria-label="删除" data-action="delete" data-index="${globalIndex}">删除</button>
        </div>
      </div>`;
    }
    function renderPlanSaveStatus() {
      return;
    }
    function markPlanOrderDirty(message = '当前排序已修改') {
      planOrderDirty = true;
    }
    function clearPlanOrderDirty(savedAt) {
      planOrderDirty = false;
    }
    function evidenceRankRange(item) {
      const ranks = (item.evidence || []).map(e => e.min_rank).filter(x => x !== null && x !== undefined);
      if (!ranks.length) return '待接入';
      return `${fmt(Math.min(...ranks))} ~ ${fmt(Math.max(...ranks))}`;
    }
    function hasValue(value) {
      return value !== null && value !== undefined && value !== '';
    }
    function firstKnownValue(...values) {
      return values.find(value => hasValue(value));
    }
    function normalizeRateValue(value) {
      if (!hasValue(value)) return '待接入';
      if (typeof value === 'number') {
        const percentValue = value > 0 && value <= 1 ? value * 100 : value;
        return `${percentValue.toFixed(percentValue % 1 === 0 ? 0 : 1)}%`;
      }
      const text = String(value).trim();
      if (!text) return '待接入';
      if (text.includes('%') || text.includes('待') || text.includes('无')) return text;
      const numberValue = Number(text);
      if (Number.isFinite(numberValue)) {
        const percentValue = numberValue > 0 && numberValue <= 1 ? numberValue * 100 : numberValue;
        return `${percentValue.toFixed(percentValue % 1 === 0 ? 0 : 1)}%`;
      }
      return text;
    }
    function disciplineAssessmentInfo(item) {
      const debug = item.debug || {};
      const identity = debug.identity || {};
      const quality = debug.discipline_quality || debug.major_quality || debug.subject_quality || {};
      const assessment = firstKnownValue(
        item['学科评估等级'],
        item['学科评估'],
        item.discipline_assessment,
        item.subject_evaluation,
        item.assessment_grade,
        item.major_assessment,
        debug['学科评估等级'],
        debug['学科评估'],
        debug.discipline_assessment,
        debug.subject_evaluation,
        debug.assessment_grade,
        debug.major_assessment,
        identity.discipline_assessment,
        identity.subject_evaluation,
        quality.discipline_assessment,
        quality.subject_evaluation,
        quality.assessment_grade,
      );
      const rate = firstKnownValue(
        item['保研率'],
        item.postgraduate_recommend_rate,
        item.postgraduate_rate,
        item.baoyan_rate,
        item.recommend_rate,
        debug['保研率'],
        debug.postgraduate_recommend_rate,
        debug.postgraduate_rate,
        debug.baoyan_rate,
        debug.recommend_rate,
        identity.postgraduate_recommend_rate,
        identity.postgraduate_rate,
        quality.postgraduate_recommend_rate,
        quality.baoyan_rate,
      );
      return {
        assessment: hasValue(assessment) ? String(assessment).trim() : '待接入',
        rate: normalizeRateValue(rate),
      };
    }
    function disciplineAssessmentHtml(item) {
      const info = disciplineAssessmentInfo(item);
      const assessmentMissing = info.assessment === '待接入';
      const rateMissing = info.rate === '待接入';
      return `<div class="discipline-assessment-cell">
        <div class="assessment-grade-line"><span>学科评估</span><b class="${assessmentMissing ? 'missing' : ''}">${escapeHtml(info.assessment)}</b></div>
        <div class="recommend-rate-line"><span>保研率</span><b class="${rateMissing ? 'missing' : ''}">${escapeHtml(info.rate)}</b></div>
      </div>`;
    }
    function planCount2026Html(item) {
      const debug = item.debug || {};
      const official = debug.plan_count_2026;
      const estimate = debug.plan_count_2026_estimated;
      const status = debug.plan_count_2026_status || '';
      if (status === 'stopped') {
        return `<span class="plan-2026-cell missing" title="${escapeHtml(debug.plan_count_2026_note || '2026 官方补充信息：该专业停止招生')}">停招</span>`;
      }
      if (hasValue(official)) {
        if (status === 'official') {
          return `<span class="plan-2026-cell official" title="2026 官方招生计划">${fmt(official)}人</span>`;
        }
        if (status === 'official_supplement') {
          return `<span class="plan-2026-cell official" title="${escapeHtml(debug.plan_count_2026_note || '2026 官方补充信息')}">调整${fmt(official)}人</span>`;
        }
        return `<span class="plan-2026-cell estimate" title="2026 招生计划参考值，来源：${escapeHtml(debug.plan_count_2026_source || '补充数据')}">参考${fmt(official)}人</span>`;
      }
      if (hasValue(estimate)) {
        return `<span class="plan-2026-cell estimate" title="官方 2026 分专业计划未接入，当前为历史计划估算值">约${fmt(estimate)}人</span>`;
      }
      return '<span class="plan-2026-cell missing" title="2026 分专业招生计划待接入">待接入</span>';
    }
    function admissionHistoryHtml(item) {
      const evidence = item.evidence || [];
      return `<div class="admission-history">${[2023, 2024, 2025].map(year => {
        const point = evidence.find(entry => Number(entry.year) === year) || {};
        const plan = hasValue(point.plan_count) ? `${fmt(point.plan_count)}人` : '待接入';
        const rank = hasValue(point.min_rank) ? `${fmt(point.min_rank)}位` : '待接入';
        return `<div class="admission-history-line"><span>${year}年:</span><b>${plan}/${rank}</b></div>`;
      }).join('')}</div>`;
    }
    function evidenceSampleNote(item) {
      const count = (item.evidence || []).filter(e => e.min_rank !== null && e.min_rank !== undefined).length;
      return count === 1 ? '<div class="mini" style="color:#a33838;">单年样本，证据不足</div>' : '';
    }
    function uniqueByOptionKey(items) {
      const seen = new Set();
      const unique = [];
      items.forEach(item => {
        if (!item || seen.has(item.option_key)) return;
        unique.push(item);
        seen.add(item.option_key);
      });
      return unique;
    }
    function invalidateReportCache() {
      selectedCartItemsCache = null;
      reportHtmlCache = { signature: '', html: '' };
    }
    function normalizeSelectedOrder() {
      const seen = new Set();
      selectedOptionOrder = selectedOptionOrder.filter(key => {
        if (!selectedOptionKeys.has(key) || seen.has(key)) return false;
        seen.add(key);
        return true;
      });
      selectedOptionKeys.forEach(key => {
        if (!seen.has(key)) {
          selectedOptionOrder.push(key);
          seen.add(key);
        }
      });
    }
    function addSelectedOption(key) {
      if (!key) return;
      selectedOptionKeys.add(key);
      if (!selectedOptionOrder.includes(key)) selectedOptionOrder.push(key);
      invalidateReportCache();
    }
    function removeSelectedOption(key) {
      selectedOptionKeys.delete(key);
      selectedOptionOrder = selectedOptionOrder.filter(item => item !== key);
      invalidateReportCache();
    }
    function clearSelectedOptions() {
      selectedOptionKeys.clear();
      selectedOptionOrder = [];
      invalidateReportCache();
    }
    function moveSelectedOption(key, delta) {
      normalizeSelectedOrder();
      const index = selectedOptionOrder.indexOf(key);
      if (index < 0) return;
      const nextIndex = Math.max(0, Math.min(selectedOptionOrder.length - 1, index + delta));
      if (nextIndex === index) return;
      const [item] = selectedOptionOrder.splice(index, 1);
      selectedOptionOrder.splice(nextIndex, 0, item);
      invalidateReportCache();
      syncRecommendationsFromSelection();
      renderMatchedUniversityRows();
      renderSelectionCart();
    }
    function moveSelectedOptionTo(key, targetPosition) {
      normalizeSelectedOrder();
      const index = selectedOptionOrder.indexOf(key);
      if (index < 0) return;
      const nextIndex = Math.max(0, Math.min(selectedOptionOrder.length - 1, Number(targetPosition) - 1));
      if (!Number.isInteger(nextIndex)) return;
      const [item] = selectedOptionOrder.splice(index, 1);
      selectedOptionOrder.splice(nextIndex, 0, item);
      invalidateReportCache();
      syncRecommendationsFromSelection();
      renderMatchedUniversityRows();
      renderSelectionCart();
    }
    function matchPercent(item) {
      if (item.success_probability !== null && item.success_probability !== undefined) {
        return Math.round(Math.max(0, Math.min(1, Number(item.success_probability) || 0)) * 100);
      }
      const risk = Math.max(0, Math.min(1, Number(item.risk_score || 0)));
      const fit = Math.max(0, Math.min(1, Number(item.fit_score || 0)));
      const stability = Math.max(0, Math.min(1, Number(item.stability_score || 0)));
      return Math.round(risk * 100);
    }
    function successRateColor(percent) {
      const value = Math.max(0, Math.min(100, Number(percent) || 0));
      const hue = Math.round(value * 1.2);
      return `hsl(${hue} 64% 42%)`;
    }
    function matchPercentHelp(item) {
      const risk = Math.round(Number(item.risk_score || 0) * 100);
      const fit = Math.round(Number(item.fit_score || 0) * 100);
      const stability = Math.round(Number(item.stability_score || 0) * 100);
      const marginText = item.rank_margin === null || item.rank_margin === undefined
        ? '历史位次不完整，所以这个分数会偏谨慎'
        : item.rank_margin >= 0
          ? `这个专业过去大约录到 ${fmt(item.weighted_reference_rank)} 名，你是 ${fmt(latestPlanData?.candidate?.rank || 0)} 名，还有约 ${fmt(item.rank_margin)} 名余量`
          : `这个专业过去大约录到 ${fmt(item.weighted_reference_rank)} 名，你还差约 ${fmt(Math.abs(item.rank_margin))} 名，属于要冲一冲`;
      const rankYears = (item.evidence || []).filter(point => point.min_rank !== null && point.min_rank !== undefined).length;
      const bandText = {
        '高冲': '5-18%',
        '冲': '18-38%',
        '稳中偏冲': '38-60%',
        '稳': '60-78%',
        '保': '78-92%',
        '强保': '92-98%',
        '证据不足': '8-20%'
      }[item.risk_band] || '8-20%';
      const percent = matchPercent(item);
      return `成功率是系统估算值，不是官方录取承诺。它先由位次差距决定风险档位和概率区间，${item.risk_band || '证据不足'} 档限定在 ${bandText}，当前估算为 ${percent}%。${marginText}；专业匹配 ${fit} 分、稳定性 ${stability} 分只在该区间内小幅调整，参考了 ${rankYears} 年有效数据。`;
    }
    function referenceRankHelp(item) {
      const validYears = (item.evidence || []).filter(point => point.min_rank !== null && point.min_rank !== undefined).map(point => point.year);
      const years = validYears.length ? validYears.join('/') : '无有效年份';
      return `可以把它理解成“这个学校专业大概需要排到多少名”。系统用了 ${years} 的历史最低位次来算，越新的年份参考更多。缺哪一年就不用哪一年；如果只有一年数据，也会正常排序，但会标出证据不足。`;
    }
    function rankMarginHelp(item) {
      return `这是“参考位次”和“你的位次”的差。正数表示你比往年录取线更靠前，有余量；负数表示你还差一些，属于冲。数字越大越稳，数字越小越冒险。`;
    }
    function riskBandHelp(item) {
      return `风险等级按位次余量分出来：差得较多是高冲/冲，接近的是稳中偏冲，有余量的是稳/保/强保。它只是按历史数据估风险，不保证录取。`;
    }
    function evidenceRangeHelp(item) {
      return `这是近几年这个学校专业最低录到的名次范围。范围越窄，说明往年比较稳定；范围越宽，说明忽高忽低，填报时要更谨慎。`;
    }
    function planChangeHelp() {
      return '现在如果还没有导入 2026 官方计划，系统只能用往年招生人数做临时参考。正式填报前一定要换成山东省考试院或学校公布的今年计划。';
    }
    function trendHelpText() {
      return '看这个专业近几年最低录到第多少名。连续变难：录取名次一年比一年靠前，说明更难进。连续变易：录取名次一年比一年靠后，说明相对变容易。波动：忽高忽低，不能只看一年。样本不足：年份太少，只能参考。';
    }
    function riskColor(risk) {
      return {
        '高冲': '#d95a62',
        '冲': '#df8440',
        '稳中偏冲': '#d6a33d',
        '稳': '#d2ac49',
        '保': '#4f8b62',
        '强保': '#7e6aa6',
        '证据不足': '#8a877e',
      }[risk] || '#8a877e';
    }
    function riskGroupCounts(counts) {
      const challenge = (counts['高冲'] || 0) + (counts['冲'] || 0) + (counts['稳中偏冲'] || 0);
      const steady = counts['稳'] || 0;
      const safe = (counts['保'] || 0) + (counts['强保'] || 0);
      const unknown = counts['证据不足'] || 0;
      return { challenge, steady, safe, unknown };
    }
    function cartRiskGroup(item) {
      if (['高冲', '冲', '稳中偏冲'].includes(item.risk_band)) return 'challenge';
      if (item.risk_band === '稳') return 'steady';
      if (['保', '强保'].includes(item.risk_band)) return 'safe';
      return 'unknown';
    }
    function selectedCartItems() {
      if (!selectedOptionKeys.size) return [];
      if (selectedCartItemsCache) return selectedCartItemsCache.slice();
      normalizeSelectedOrder();
      const byKey = new Map([...searchRecommendations, ...candidateRecommendations, ...currentRecommendations, ...systemRecommendations].map(item => [item.option_key, item]));
      selectedCartItemsCache = selectedOptionOrder.map(key => byKey.get(key)).filter(Boolean);
      return selectedCartItemsCache.slice();
    }
    function cartCounts(items) {
      const counts = {};
      items.forEach(item => {
        counts[item.risk_band] = (counts[item.risk_band] || 0) + 1;
      });
      return riskGroupCounts(counts);
    }
    function selectedReviewCount(items) {
      return items.filter(item => {
        const debug = item.debug || {};
        return (item.warnings || []).length || (debug.plan_count_2026_status && debug.plan_count_2026_status !== 'official') || planAuditLevel(item) !== 'low';
      }).length;
    }
    function selectedCharterCount(items) {
      return items.filter(item => {
        const info = charterInfo(item);
        return info.status !== 'verified' || (info.rules || []).length;
      }).length;
    }
    function cartGuidance(items, groups) {
      if (!items.length) return '从左侧匹配列表勾选，右侧实时汇总。';
      const target = targetVolunteerSize();
      const safeTarget = Math.max(8, Math.round(target * 0.2));
      const stable = groups.steady + groups.safe;
      if (groups.safe < safeTarget) return `已选 ${fmt(items.length)} 个，保底项建议继续补到 ${fmt(safeTarget)} 个左右。`;
      if (groups.challenge > stable) return '冲刺项偏多，建议继续补充稳和保。';
      return '已选结构较清楚，可打开清单继续微调。';
    }
    function cartPreviewItemHtml(item) {
      const meta = schoolMeta(item);
      const rank = item.weighted_reference_rank ? `参考 ${fmt(item.weighted_reference_rank)}` : '参考位次待接入';
      return `<div class="cart-preview-item">
        <div>
          <b>${escapeHtml(optionMajor(item))}</b>
          <span class="mini">${escapeHtml(meta.school)} · ${escapeHtml(meta.city)} · ${rank}</span>
        </div>
        <span class="drawer-risk-pill" style="background:${riskColor(item.risk_band)}">${escapeHtml(item.risk_band)}</span>
      </div>`;
    }
    function drawerInfoCellHtml(label, content, className = '') {
      return `<div class="drawer-info-cell ${className}">
        <span class="drawer-info-label">${escapeHtml(label)}</span>
        <div class="drawer-info-value">${content}</div>
      </div>`;
    }
    function drawerItemHtml(item, index, total) {
      const meta = schoolMeta(item);
      const codes = optionCodes(item);
      const rank = item.weighted_reference_rank ? `参考位次 ${fmt(item.weighted_reference_rank)}` : '参考位次待接入';
      const codeText = `${escapeHtml(codes.schoolCode)} / ${escapeHtml(codes.majorCode)}`;
      const levelTags = schoolLevelTags(item);
      const levelHtml = `<div class="school-tags level-tags">${levelTags.length ? schoolTagHtml(levelTags) : '<span class="school-tag">本科</span>'}</div>`;
      return `<div class="drawer-item">
        <span class="drawer-order-index">${fmt(index + 1)}</span>
        <div class="drawer-item-main">
          <b>${escapeHtml(optionMajor(item))}</b>
          <span class="mini">${escapeHtml(meta.school)} · ${escapeHtml(meta.city)} · ${codeText}</span>
          <span class="mini">${rank} · ${escapeHtml(optionIdentity(item))}</span>
          ${charterCompactHtml(item, 2)}
        </div>
        ${drawerInfoCellHtml('院校层次', levelHtml, 'drawer-school-level')}
        ${drawerInfoCellHtml('招生人数', planCount2026Html(item), 'drawer-plan-count')}
        ${drawerInfoCellHtml('学科评价', disciplineAssessmentHtml(item), 'drawer-discipline-quality')}
        <div class="drawer-item-risk" aria-label="冲稳保">
          <span class="drawer-risk-title">冲稳保</span>
          <span class="drawer-risk-pill" style="background:${riskColor(item.risk_band)}">${escapeHtml(item.risk_band)}</span>
        </div>
        <div class="drawer-item-tools">
          <div class="drawer-move-row" aria-label="调整志愿顺序">
            <button type="button" data-cart-move="${escapeHtml(item.option_key)}" data-cart-delta="-1" ${index <= 0 ? 'disabled' : ''} title="上移" aria-label="上移">↑</button>
            <button type="button" data-cart-move="${escapeHtml(item.option_key)}" data-cart-delta="1" ${index >= total - 1 ? 'disabled' : ''} title="下移" aria-label="下移">↓</button>
            <div class="drawer-move-control">
              <input data-cart-position="${escapeHtml(item.option_key)}" inputmode="numeric" value="${index + 1}" aria-label="目标位次">
              <button type="button" data-cart-jump="${escapeHtml(item.option_key)}" title="移动到输入位次" aria-label="移动到输入位次">↵</button>
            </div>
          </div>
          <button type="button" class="drawer-remove" data-cart-remove="${escapeHtml(item.option_key)}">移除</button>
        </div>
      </div>`;
    }
    function drawerOrderedListHtml(items) {
      return `<section class="drawer-group">
        <div class="drawer-group-head"><b>志愿顺序</b><span>${fmt(items.length)} 个</span></div>
        <div class="drawer-list">${items.map((item, index) => drawerItemHtml(item, index, items.length)).join('')}</div>
      </section>`;
    }
    function renderSelectionCart() {
      const totalBadge = document.getElementById('selectionCartTotal');
      if (!totalBadge) return;
      const items = selectedCartItems();
      const groups = cartCounts(items);
      const total = Math.max(0, items.length);
      const target = targetVolunteerSize();
      const reviewCount = selectedReviewCount(items);
      const charterCount = selectedCharterCount(items);
      totalBadge.textContent = `已选 ${fmt(total)}/${fmt(target)}`;
      document.getElementById('selectionCartHint').textContent = cartGuidance(items, groups);
      document.getElementById('selectionCartChallenge').textContent = fmt(groups.challenge);
      document.getElementById('selectionCartSteady').textContent = fmt(groups.steady);
      document.getElementById('selectionCartSafe').textContent = fmt(groups.safe);
      document.getElementById('selectionReviewChip').textContent = `复核 ${fmt(reviewCount)}`;
      document.getElementById('selectionCharterChip').textContent = `章程 ${fmt(charterCount)}`;
      const stack = document.getElementById('selectionCartStack');
      const parts = [
        ['challenge', groups.challenge],
        ['steady', groups.steady],
        ['safe', groups.safe],
        ['unknown', groups.unknown],
      ].filter(([, value]) => value > 0);
      stack.innerHTML = parts.length
        ? parts.map(([name, value]) => `<span class="${name}" style="width:${(value / total) * 100}%"></span>`).join('')
        : '<span class="unknown" style="width:100%"></span>';
      const preview = document.getElementById('selectionCartPreview');
      preview.innerHTML = items.length
        ? items.slice(0, 4).map(cartPreviewItemHtml).join('') + (items.length > 4 ? `<div class="mini">另有 ${fmt(items.length - 4)} 个，打开清单查看。</div>` : '')
        : '<div class="cart-empty">还没有加入志愿，先在左侧列表勾选。</div>';
      document.getElementById('drawerChallengeCount').textContent = fmt(groups.challenge);
      document.getElementById('drawerSteadyCount').textContent = fmt(groups.steady);
      document.getElementById('drawerSafeCount').textContent = fmt(groups.safe);
      document.getElementById('selectionDrawerSub').textContent = `已选 ${fmt(total)} 个 · 复核 ${fmt(reviewCount)} · 章程 ${fmt(charterCount)} · 可调顺序和宽度`;
      document.getElementById('selectionDrawerGroups').innerHTML = items.length
        ? drawerOrderedListHtml(items)
        : '<div class="drawer-empty">还没有加入志愿。回到选择学校专业列表，勾选想保留的学校专业。</div>';
      const dockCount = document.getElementById('cartDockCount');
      if (dockCount) dockCount.textContent = fmt(total);
      const dockButton = document.getElementById('cartDockButton');
      if (dockButton) dockButton.classList.toggle('has-items', total > 0);
      syncSelectionCartLayout();
    }
    function syncSelectionCartLayout() {
      const grid = document.querySelector('.grid');
      const drawer = document.getElementById('selectionDrawer');
      const dockButton = document.getElementById('cartDockButton');
      const pinButton = document.getElementById('pinSelectionCart');
      const drawerOpen = Boolean(drawer && drawer.classList.contains('open'));
      if (grid) grid.classList.toggle('cart-pinned', selectionCartPinned);
      if (dockButton) dockButton.classList.toggle('hidden', selectionCartPinned || drawerOpen);
      if (pinButton) {
        pinButton.textContent = selectionCartPinned ? '已固定' : '固定侧栏';
        pinButton.disabled = selectionCartPinned;
      }
    }
    function drawerWidthBounds() {
      const viewport = Math.max(320, window.innerWidth || document.documentElement.clientWidth || 1280);
      return {
        min: Math.round(viewport * 0.30),
        max: Math.round(viewport * 0.70),
      };
    }
    function clampDrawerWidth(width) {
      const bounds = drawerWidthBounds();
      return Math.max(bounds.min, Math.min(bounds.max, Math.round(width)));
    }
    function applyDrawerWidth(width = selectionDrawerWidth) {
      const drawer = document.getElementById('selectionDrawer');
      selectionDrawerWidth = clampDrawerWidth(width);
      if (drawer) drawer.style.setProperty('--selection-drawer-width', `${selectionDrawerWidth}px`);
    }
    function startDrawerResize(event) {
      if (event.button !== undefined && event.button !== 0) return;
      const drawer = document.getElementById('selectionDrawer');
      if (!drawer) return;
      const rect = drawer.getBoundingClientRect();
      drawerResizeState = {
        startX: event.clientX,
        startWidth: rect.width,
      };
      drawer.classList.add('resizing');
      event.preventDefault();
      if (event.pointerId !== undefined && event.currentTarget.setPointerCapture) {
        event.currentTarget.setPointerCapture(event.pointerId);
      }
    }
    function handleDrawerResizeMove(event) {
      if (!drawerResizeState) return;
      const nextWidth = drawerResizeState.startWidth + (drawerResizeState.startX - event.clientX);
      applyDrawerWidth(nextWidth);
    }
    function stopDrawerResize() {
      if (!drawerResizeState) return;
      drawerResizeState = null;
      const drawer = document.getElementById('selectionDrawer');
      if (drawer) drawer.classList.remove('resizing');
    }
    function openSelectionDrawer() {
      applyDrawerWidth();
      renderSelectionCart();
      document.getElementById('selectionDrawer').classList.add('open');
      document.getElementById('selectionDrawer').setAttribute('aria-hidden', 'false');
      document.getElementById('selectionDrawerBackdrop').classList.add('open');
      syncSelectionCartLayout();
    }
    function closeSelectionDrawer() {
      document.getElementById('selectionDrawer').classList.remove('open');
      document.getElementById('selectionDrawer').setAttribute('aria-hidden', 'true');
      document.getElementById('selectionDrawerBackdrop').classList.remove('open');
      syncSelectionCartLayout();
    }
    function settingsPanelSummary(panel) {
      if (panel === 'profile') return profileFilterSummaryText();
      return `当前：${strategyLabels[currentStrategy()] || currentStrategy()}`;
    }
    function openSettingsSlide(panel = 'strategy') {
      activeSettingsPanel = panel === 'profile' ? 'profile' : 'strategy';
      const title = activeSettingsPanel === 'profile' ? '详细筛选条件' : '方案设定';
      document.getElementById('settingsSlideTitle').textContent = title;
      document.getElementById('settingsSlideSummary').textContent = settingsPanelSummary(activeSettingsPanel);
      document.querySelectorAll('[data-settings-panel]').forEach(section => {
        section.hidden = section.dataset.settingsPanel !== activeSettingsPanel;
      });
      document.getElementById('settingsSlidePanel').classList.add('open');
      document.getElementById('settingsSlidePanel').setAttribute('aria-hidden', 'false');
      document.getElementById('settingsSlideBackdrop').classList.add('open');
    }
    function closeSettingsSlide() {
      document.getElementById('settingsSlidePanel').classList.remove('open');
      document.getElementById('settingsSlidePanel').setAttribute('aria-hidden', 'true');
      document.getElementById('settingsSlideBackdrop').classList.remove('open');
    }
    function pinSelectionCartSidebar() {
      selectionCartPinned = true;
      closeSelectionDrawer();
      renderSelectionCart();
    }
    function unpinSelectionCartSidebar() {
      selectionCartPinned = false;
      syncSelectionCartLayout();
    }
    function clearSelectedCart() {
      if (!selectedOptionKeys.size) {
        alert('当前还没有加入大学。');
        return;
      }
      if (!confirm(`确定清空已选的 ${fmt(selectedOptionKeys.size)} 个大学专业吗？`)) return;
      clearSelectedOptions();
      matchedPage = 1;
      syncRecommendationsFromSelection();
      renderMatchedUniversityRows();
      renderSelectionCart();
    }
    function auditLevelLabel(level) {
      return level === 'high' ? '高风险' : level === 'medium' ? '需复核' : '低风险';
    }
    function planAuditLevel(item) {
      const debug = item.debug || {};
      const charter = debug.charter_level || 'low';
      const warnings = item.warnings || [];
      if (debug.plan_count_2026_status === 'stopped') return 'high';
      if (charter === 'high' || warnings.some(text => String(text).includes('计划数低于'))) return 'high';
      if (charter === 'medium' || warnings.length || debug.plan_count_2026_status !== 'official') return 'medium';
      return 'low';
    }
    function equivalentSparkline(items, activeIndex) {
      const scores = items.map(item => Number(item.score)).filter(Number.isFinite);
      if (scores.length < 2) return '<span class="mini">样本不足</span>';
      const min = Math.min(...scores);
      const max = Math.max(...scores);
      const range = Math.max(1, max - min);
      const points = items.map((item, index) => {
        const x = 10 + (index * 94) / Math.max(1, items.length - 1);
        const y = 26 - ((Number(item.score) - min) / range) * 18;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(' ');
      const point = points.split(' ')[activeIndex] || points.split(' ').at(-1);
      const [cx, cy] = point.split(',');
      return `<svg class="sparkline" viewBox="0 0 118 34" aria-label="等效分趋势"><polyline points="${points}"></polyline><circle cx="${cx}" cy="${cy}" r="3.2"></circle></svg>`;
    }
    function applyUrlParams() {
      const params = new URLSearchParams(window.location.search);
      const rank = params.get('rank');
      if (rank && /^[1-9]\d*$/.test(rank)) {
        form.elements.rank.value = rank;
      }
      const subjects = params.get('subjects');
      if (subjects) {
        const next = splitTerms(subjects).filter(item => subjectOptions.includes(item)).slice(0, 3);
        if (next.length === 3) selectedSubjects = next;
      }
      const interests = params.get('interests');
      if (interests) {
        const next = splitTerms(interests);
        if (next.length) selectedInterests = Array.from(new Set(next));
      }
      const customQuotas = params.get('custom_quotas');
      if (customQuotas) {
        try {
          const quotas = JSON.parse(customQuotas);
          customQuotaFields.forEach(field => {
            if (form.elements[field.name] && quotas[field.band] !== undefined) {
              form.elements[field.name].value = Math.max(0, Number(quotas[field.band]) || 0);
            }
          });
        } catch (error) {
          console.warn('忽略无效自定义方案数量', error);
        }
      }
      const customRiskGaps = params.get('custom_risk_gaps');
      if (customRiskGaps) {
        try {
          const gaps = JSON.parse(customRiskGaps);
          const readGap = (key, fallback) => {
            const value = Number(gaps[key]);
            return Number.isFinite(value) ? Math.max(0, Math.floor(value)) : fallback;
          };
          customGapNumbers = {
            challenge: readGap('challenge', customGapNumbers.challenge),
            steady: readGap('steady', customGapNumbers.steady),
            safe: readGap('safe', customGapNumbers.safe),
          };
        } catch (error) {
          console.warn('忽略无效自定义分差设定', error);
        }
      }
      ['strategy', 'targetSize', 'bandWidth', 'maxTuition', 'preferredCities', 'blockedCities', 'avoidKeywords', 'priority'].forEach(name => {
        const value = params.get(name);
        if (value !== null && form.elements[name]) form.elements[name].value = value;
      });
      ['allowPrivate', 'allowSinoForeign', 'requireDoubleFirstClass', 'require985', 'require211', 'requirePublicUndergrad'].forEach(name => {
        const value = params.get(name);
        if (value !== null && form.elements[name]) form.elements[name].checked = ['1', 'true', 'yes', 'on'].includes(value);
      });
    }
    async function loadMajorCatalog() {
      try {
        const response = await fetch('/majors-data');
        if (!response.ok) throw new Error(await response.text());
        const payload = await response.json();
        majorCatalog = payload.majors || [];
        admissionMajorCatalog = payload.admission_major_names || [];
        majorSelectionCache = [];
        const summary = `教育部 2026 本科专业目录：${calcValue(fmt(payload.count || majorCatalog.length), '系统现在可识别的本科专业数量。专业名称以教育部正式目录为准。')} 个专业 · 数据以教育部 PDF 附件为准`;
        const summaryEl = document.getElementById('majorCatalogSummary');
        if (summaryEl) summaryEl.innerHTML = summary;
        const disciplines = Array.from(new Set(majorCatalog.map(item => item.discipline).filter(Boolean)));
        const disciplineEl = document.getElementById('majorDiscipline');
        if (disciplineEl) {
          disciplineEl.innerHTML = '<option value="">全部门类</option>' + disciplines.map(item => `<option value="${item}">${item}</option>`).join('');
        }
        if (selectedInterests.length) setSelectedInterests(selectedInterests);
        else {
          syncInterests();
          renderInterestOptions();
          renderMajorSelector();
        }
      } catch (error) {
        const summaryEl = document.getElementById('majorCatalogSummary');
        if (summaryEl) summaryEl.textContent = '2026 本科专业目录读取失败，请刷新页面。';
        majorCatalog = [];
        admissionMajorCatalog = [];
        majorSelectionCache = [];
      }
    }
    function majorText(major) {
      return [major.name, major.category, major.discipline, major.code].join(' ');
    }
    function normalizeMajorSearchText(value) {
      return String(value || '').toLowerCase().replace(/[（）]/g, char => (char === '（' ? '(' : ')')).trim();
    }
    function baseMajorName(value) {
      return String(value || '').replace(/[（(].*?[）)]/g, '').trim();
    }
    function parentheticalText(value) {
      const match = String(value || '').match(/[（(](.*?)[）)]/);
      return match ? match[1].trim() : '';
    }
    function addUnique(list, value) {
      const text = String(value || '').trim();
      if (text && text.length >= 2 && !list.includes(text)) list.push(text);
    }
    function majorSelectionItems() {
      if (majorSelectionCache.length) return majorSelectionCache;
      const items = [];
      (majorCatalog || []).forEach(item => {
        const name = String(item.name || '').trim();
        if (!name) return;
        const code = String(item.code || '').trim();
        const category = String(item.category || '').trim();
        const discipline = String(item.discipline || '').trim();
        items.push({
          kind: 'standard',
          name,
          code,
          category,
          discipline,
          group: `${discipline || '未分类'} / ${category || '未分类'}`,
          badge: '标准',
          displayMeta: `${code || '无代码'} · ${category || discipline || '教育部标准专业'}`,
          searchText: normalizeMajorSearchText([name, code, category, discipline, '教育部', '标准专业'].join(' ')),
        });
      });
      (admissionMajorCatalog || []).forEach(item => {
        const name = String(item.name || '').trim();
        if (!name) return;
        const latestYear = item.latest_year ? `${item.latest_year}年` : '';
        const count = item.count ? `${fmt(item.count)}条记录` : '';
        items.push({
          kind: 'admission',
          name,
          code: '',
          category: '山东招生专业名称',
          discipline: '山东普通类常规批',
          group: '山东发布招生专业名称',
          badge: '山东',
          displayMeta: ['山东发布名称', latestYear, count].filter(Boolean).join(' · '),
          searchText: normalizeMajorSearchText([name, latestYear, count, '山东', '投档', '招生专业'].join(' ')),
        });
      });
      const seen = new Set();
      majorSelectionCache = items.filter(item => {
        if (seen.has(item.name)) return false;
        seen.add(item.name);
        return true;
      });
      return majorSelectionCache;
    }
    function majorSelectionItemByName(name) {
      return majorSelectionItems().find(item => item.name === name) || null;
    }
    function majorSelectionKeywordParts(name, item = majorSelectionItemByName(name)) {
      const parts = [];
      addUnique(parts, name);
      addUnique(parts, baseMajorName(name));
      addUnique(parts, parentheticalText(name));
      if (selectedMajorAliasMap[name]) selectedMajorAliasMap[name].forEach(alias => addUnique(parts, alias));
      if (majorInterestAliases[name]) majorInterestAliases[name].forEach(alias => addUnique(parts, alias));
      if (item) {
        addUnique(parts, item.category);
        if (item.category && item.category.endsWith('类')) addUnique(parts, item.category.replace(/类$/, ''));
      }
      if (name.endsWith('科学与技术')) addUnique(parts, name.replace('科学与技术', ''));
      if (name.endsWith('工程')) addUnique(parts, name.replace('工程', ''));
      if (name.endsWith('学')) addUnique(parts, name.replace(/学$/, ''));
      return parts;
    }
    function selectionNamesForKeyword(keyword, limit = 18) {
      const term = String(keyword || '').trim();
      if (!term) return [];
      const items = majorSelectionItems();
      if (items.some(item => item.name === term)) return [term];
      const aliases = Array.from(new Set([term, ...(majorInterestAliases[term] || [])]));
      const normalizedAliases = aliases.map(normalizeMajorSearchText).filter(Boolean);
      const matches = items.filter(item =>
        normalizedAliases.some(alias => item.searchText.includes(alias) || normalizeMajorSearchText(item.name).includes(alias))
      );
      return matches
        .sort((a, b) => {
          if (a.kind !== b.kind) return a.kind === 'standard' ? -1 : 1;
          return a.name.length - b.name.length || a.name.localeCompare(b.name, 'zh-CN');
        })
        .slice(0, limit)
        .map(item => item.name);
    }
    function interestKeywords() {
      const keywords = [];
      selectedInterests.forEach(item => {
        majorSelectionKeywordParts(item).forEach(part => addUnique(keywords, part));
        (majorInterestAliases[item] || []).forEach(part => addUnique(keywords, part));
      });
      return keywords;
    }
    function majorMatchesInterests(major) {
      const text = majorText(major);
      const keywords = interestKeywords();
      if (!keywords.length) return true;
      return keywords.some(keyword => keyword && text.includes(keyword));
    }
    function majorKeywordParts(name) {
      return majorSelectionKeywordParts(name);
    }
    function candidateText(item) {
      const debug = item.debug || {};
      return [
        item.option_name,
        optionMajor(item),
        ...(item.reasons || []),
        ...(debug.tags || []),
        ...(debug.subjects || []),
      ].join(' ');
    }
    function candidateMatchesSelectedMajors(item) {
      const text = candidateText(item);
      if (!selectedMajors.length) {
        const keywords = interestKeywords();
        return !keywords.length || keywords.some(keyword => keyword && text.includes(keyword)) || systemRecommendations.some(auto => auto.option_key === item.option_key);
      }
      return selectedMajors.some(name => majorKeywordParts(name).some(part => text.includes(part)));
    }
    function searchTerms() {
      return candidateSearchText
        .trim()
        .toLowerCase()
        .split(/[,\s，、;；/]+/)
        .map(term => term.trim())
        .filter(Boolean);
    }
    function candidateMatchesSearch(item) {
      const terms = searchTerms();
      if (!terms.length) return true;
      const meta = schoolMeta(item);
      const haystack = [
        candidateText(item),
        meta.school,
        meta.city,
        ...(meta.tags || []),
        item.risk_band,
        item.option_key,
      ].join(' ').toLowerCase();
      return terms.every(term => haystack.includes(term));
    }
    function candidateMatchesRiskFilter(item) {
      if (candidateRiskFilter === 'all') return true;
      if (candidateRiskFilter === 'challenge') return ['高冲', '冲', '稳中偏冲'].includes(item.risk_band);
      if (candidateRiskFilter === 'steady') return item.risk_band === '稳';
      if (candidateRiskFilter === 'safe') return ['保', '强保'].includes(item.risk_band);
      if (candidateRiskFilter === 'selected') return selectedOptionKeys.has(item.option_key);
      return true;
    }
    function selectedMajorObjects() {
      const selected = new Set(selectedMajors);
      return majorCatalog.filter(item => selected.has(item.name));
    }
    function renderMajorSelector() {
      if (!document.getElementById('majorGroups')) return;
      if (!majorCatalog.length) {
        document.getElementById('majorGroups').innerHTML = '<div class="mini">专业目录尚未加载。</div>';
        return;
      }
      const query = document.getElementById('majorSearch').value.trim().toLowerCase();
      const discipline = document.getElementById('majorDiscipline').value;
      let items = majorCatalog.filter(item => {
        if (discipline && item.discipline !== discipline) return false;
        if (query) return majorText(item).toLowerCase().includes(query);
        return majorMatchesInterests(item);
      });
      recommendedMajorNames = majorCatalog.filter(majorMatchesInterests).map(item => item.name);
      if (!items.length && !query) items = majorCatalog.slice(0, 80);
      items = items.slice(0, query ? 180 : 120);
      const selected = new Set(selectedMajors);
      const grouped = new Map();
      items.forEach(item => {
        const key = `${item.discipline} / ${item.category}`;
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push(item);
      });
      document.getElementById('majorSelectionNote').innerHTML = [
        `<span class="filter-pill">${selectedInterests.length ? '专业推荐' : '不限专业'} ${fmt(recommendedMajorNames.length)} 个专业</span>`,
        `<span class="filter-pill">已选 ${fmt(selectedMajors.length)} 个专业</span>`,
        selectedMajors.length ? `<span class="filter-pill">${selectedMajors.slice(0, 6).join('、')}${selectedMajors.length > 6 ? ' 等' : ''}</span>` : '<span class="filter-pill">未选择专业：默认不限制专业范围</span>',
      ].join('');
      document.getElementById('majorGroups').innerHTML = Array.from(grouped.entries()).map(([group, groupItems]) => `
        <section class="major-group">
          <div class="major-group-head"><b>${group}</b><span class="mini">${fmt(groupItems.length)} 个</span></div>
          <div class="major-options">
            ${groupItems.map(item => `<label class="major-option ${selected.has(item.name) ? 'selected' : ''}">
              <input type="checkbox" data-major-name="${item.name}" ${selected.has(item.name) ? 'checked' : ''}>
              <span><b>${item.name}</b><span>${item.code} · ${item.category}</span></span>
            </label>`).join('')}
          </div>
        </section>
      `).join('') || '<div class="mini">没有匹配专业，请换一个关键词。</div>';
    }
    function filteredCandidateRecommendations() {
      if (candidateRiskFilter === 'selected') {
        return selectedCartItems().filter(candidateMatchesSearch);
      }
      const bySuccessAscending = (a, b) =>
        matchPercent(a) - matchPercent(b)
        || riskOrder.indexOf(a.risk_band) - riskOrder.indexOf(b.risk_band)
        || Number(a.weighted_reference_rank || 0) - Number(b.weighted_reference_rank || 0);
      if (freeSelectionMode) {
        const pool = searchRecommendations.length ? searchRecommendations : candidateRecommendations;
        return pool.filter(candidateMatchesSearch).slice().sort(bySuccessAscending);
      }
      const base = candidateSearchText.trim()
        ? candidateRecommendations
        : candidateRecommendations.filter(candidateMatchesSelectedMajors);
      return base.filter(candidateMatchesSearch).filter(candidateMatchesRiskFilter).slice().sort(bySuccessAscending);
    }
    function candidateRiskFilterLabel(value) {
      return {
        all: '全部',
        challenge: '冲',
        steady: '稳',
        safe: '保',
        selected: '已选',
      }[value] || value;
    }
    function matchedEmptyMessage() {
      if (candidateRiskFilter === 'selected') {
        return '还没有加入大学。可以回到“全部/冲/稳/保”中加入候选。';
      }
      const terms = searchTerms();
      const causes = [];
      if (terms.length) causes.push(`关键词“${escapeHtml(terms.join(' + '))}”没有同时命中候选`);
      if (freeSelectionMode) causes.push('自由选择模式下仍没有匹配关键词的候选');
      if (!freeSelectionMode && candidateRiskFilter !== 'all') causes.push(`当前只看“${escapeHtml(candidateRiskFilterLabel(candidateRiskFilter))}”档`);
      if (!terms.length && selectedMajors.length) {
        const text = `${selectedMajors.slice(0, 4).join('、')}${selectedMajors.length > 4 ? '等' : ''}`;
        causes.push(`已选专业“${escapeHtml(text)}”没有命中候选`);
      }
      if (!terms.length && !selectedMajors.length && selectedInterests.length) {
        const text = `${selectedInterests.slice(0, 4).join('、')}${selectedInterests.length > 4 ? '等' : ''}`;
        causes.push(`专业选择“${escapeHtml(text)}”在当前分数带内没有可显示候选`);
      }
      const reason = causes.length ? `无数据：${causes.join('；')}。` : '无数据。';
      const activePool = freeSelectionMode && searchRecommendations.length ? searchRecommendations : candidateRecommendations;
      const baseCount = activePool.length ? `本轮后端实际生成了 ${fmt(activePool.length)} 条候选，` : '';
      return `${baseCount}${reason}可以清空关键词、切回“全部”，或放宽专业选择/分数区间后重新生成。`;
    }
    function currentPageSize() {
      return PAGE_SIZE_OPTIONS.includes(pageSize) ? pageSize : PAGE_SIZE_OPTIONS[0];
    }
    function totalPages(totalItems) {
      return Math.max(1, Math.ceil(totalItems / currentPageSize()));
    }
    function clampPage(page, totalItems) {
      return Math.min(Math.max(1, page), totalPages(totalItems));
    }
    function pageWindow(items, page) {
      const current = clampPage(page, items.length);
      const size = currentPageSize();
      const start = (current - 1) * size;
      const end = Math.min(items.length, start + size);
      return { current, start, end, items: items.slice(start, end) };
    }
    function renderPagination(containerId, target, page, totalItems) {
      const container = document.getElementById(containerId);
      if (!container) return;
      const pages = totalPages(totalItems);
      const current = clampPage(page, totalItems);
      const size = currentPageSize();
      const pageSizeOptions = PAGE_SIZE_OPTIONS.map(sizeOption => `
        <option value="${sizeOption}" ${sizeOption === size ? 'selected' : ''}>${fmt(sizeOption)} 条</option>`).join('');
      container.innerHTML = `
        <div class="pagination-summary">
          <strong>第 ${fmt(current)} / ${fmt(pages)} 页</strong>
          <span>共 ${fmt(totalItems)} 条</span>
        </div>
        <div class="page-jump-control" aria-label="跳转页码">
          <span>跳至</span>
          <input type="number" min="1" max="${pages}" value="${current}" inputmode="numeric" data-page-jump-target="${target}" aria-label="跳转到第几页" ${pages <= 1 ? 'disabled' : ''}>
          <span>页</span>
          <button type="button" data-page-target="${target}" data-page-value="jump" ${pages <= 1 ? 'disabled' : ''}>跳转</button>
        </div>
        <div class="pagination-actions" role="group" aria-label="分页控制">
          <button type="button" data-page-target="${target}" data-page-value="prev" ${current <= 1 ? 'disabled' : ''} aria-label="上一页" title="上一页">&lsaquo;</button>
          <button type="button" data-page-target="${target}" data-page-value="next" ${current >= pages ? 'disabled' : ''} aria-label="下一页" title="下一页">&rsaquo;</button>
        </div>
        <label class="page-size-control">
          <span>每页</span>
          <select data-page-size-target="${target}" aria-label="每页显示条数">
            ${pageSizeOptions}
          </select>
        </label>`;
    }
    function resolvePageAction(value, current, totalItems) {
      const pages = totalPages(totalItems);
      if (value === 'first') return 1;
      if (value === 'prev') return Math.max(1, current - 1);
      if (value === 'next') return Math.min(pages, current + 1);
      if (value === 'last') return pages;
      const page = Number(value);
      return Number.isFinite(page) ? clampPage(page, totalItems) : current;
    }
    function syncRecommendationsFromSelection() {
      if (selectedOptionKeys.size) {
        currentRecommendations = selectedCartItems().map(item => ({ ...item }));
      } else {
        currentRecommendations = systemRecommendations.map(item => ({ ...item }));
      }
      recommendationPage = 1;
      renderSortRows();
      renderInterestPreview();
      renderSelectionCart();
      markPlanOrderDirty();
    }
    function syncSelectedOrderFromCurrentRecommendations() {
      if (!selectedOptionKeys.size) return;
      const ordered = currentRecommendations
        .map(item => item.option_key)
        .filter(key => selectedOptionKeys.has(key));
      const seen = new Set(ordered);
      selectedOptionOrder = [
        ...ordered,
        ...selectedOptionOrder.filter(key => selectedOptionKeys.has(key) && !seen.has(key)),
      ];
      normalizeSelectedOrder();
      invalidateReportCache();
    }
    function customQuotaValues() {
      const quotas = {};
      customQuotaFields.forEach(field => {
        const input = form.elements[field.name];
        const value = Number(input && input.value);
        quotas[field.band] = Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
      });
      return quotas;
    }
    function customQuotaTotal() {
      return Object.values(customQuotaValues()).reduce((sum, value) => sum + value, 0);
    }
    function quotaTotal(quotas) {
      return Object.values(quotas || {}).reduce((sum, value) => sum + Math.max(0, Number(value) || 0), 0);
    }
    function quotaGroupCounts(quotas) {
      return {
        challenge: Number(quotas['高冲'] || 0) + Number(quotas['冲'] || 0) + Number(quotas['稳中偏冲'] || 0),
        steady: Number(quotas['稳'] || 0),
        safe: Number(quotas['保'] || 0) + Number(quotas['强保'] || 0),
      };
    }
    function groupTotal(groups) {
      return ['challenge', 'steady', 'safe'].reduce((sum, key) => sum + Math.max(0, Number(groups[key]) || 0), 0);
    }
    function ratioPercentagesFromGroups(groups) {
      const keys = ['challenge', 'steady', 'safe'];
      const total = keys.reduce((sum, key) => sum + Math.max(0, Number(groups[key]) || 0), 0);
      if (!total) return { challenge: 0, steady: 0, safe: 0 };
      const parts = keys.map(key => {
        const exact = Math.max(0, Number(groups[key]) || 0) * 100 / total;
        return { key, value: Math.floor(exact), fraction: exact - Math.floor(exact) };
      });
      let remainder = 100 - parts.reduce((sum, part) => sum + part.value, 0);
      parts.slice().sort((a, b) => b.fraction - a.fraction).forEach(part => {
        if (remainder > 0) {
          part.value += 1;
          remainder -= 1;
        }
      });
      return Object.fromEntries(parts.map(part => [part.key, part.value]));
    }
    function ratioPercentagesFromQuotas(quotas) {
      return ratioPercentagesFromGroups(quotaGroupCounts(quotas || {}));
    }
    function strategyGroupCounts(key, item) {
      if (item && item.quotas) {
        return quotaGroupCounts(item.quotas);
      }
      if (item) {
        return {
          challenge: Number(item.challenge_count || 0),
          steady: Number(item.steady_count || 0),
          safe: Number(item.safe_count || 0),
        };
      }
      if (key === 'custom') return customGroupCountValues();
      return scaleGroupsToTotal(quotaGroupCounts(strategyBaseQuotas[key] || strategyBaseQuotas.balanced), currentTargetSizeInput());
    }
    function strategyRatioPercentages(key, item) {
      return ratioPercentagesFromGroups(strategyGroupCounts(key, item));
    }
    function readPositiveInteger(value, fallback = 0) {
      const number = Number(String(value ?? '').trim());
      return Number.isFinite(number) ? Math.max(0, Math.floor(number)) : fallback;
    }
    function currentTargetSizeInput() {
      return Math.max(1, readPositiveInteger(form.elements.targetSize && form.elements.targetSize.value, 96) || 96);
    }
    function distributeCount(total, parts) {
      const safeTotal = Math.max(0, Math.floor(Number(total) || 0));
      const weightTotal = parts.reduce((sum, part) => sum + Math.max(0, Number(part.weight) || 0), 0);
      if (!safeTotal || !weightTotal) {
        return Object.fromEntries(parts.map(part => [part.name, 0]));
      }
      const rows = parts.map(part => {
        const exact = safeTotal * Math.max(0, Number(part.weight) || 0) / weightTotal;
        return { ...part, value: Math.floor(exact), fraction: exact - Math.floor(exact) };
      });
      let remainder = safeTotal - rows.reduce((sum, row) => sum + row.value, 0);
      rows.slice().sort((a, b) => b.fraction - a.fraction).forEach(row => {
        if (remainder > 0) {
          row.value += 1;
          remainder -= 1;
        }
      });
      return Object.fromEntries(rows.map(row => [row.name, row.value]));
    }
    function scaleGroupsToTotal(groups, target) {
      const safeTarget = Math.max(1, Math.floor(Number(target) || 1));
      const total = groupTotal(groups);
      const weights = total > 0 ? groups : { challenge: 44, steady: 31, safe: 25 };
      return distributeCount(safeTarget, [
        { name: 'challenge', weight: weights.challenge },
        { name: 'steady', weight: weights.steady },
        { name: 'safe', weight: weights.safe },
      ]);
    }
    function customGroupCountValues() {
      const inputs = {
        challenge: document.querySelector('[data-custom-count="challenge"]'),
        steady: document.querySelector('[data-custom-count="steady"]'),
        safe: document.querySelector('[data-custom-count="safe"]'),
      };
      if (inputs.challenge || inputs.steady || inputs.safe) {
        return {
          challenge: readPositiveInteger(inputs.challenge?.value, 0),
          steady: readPositiveInteger(inputs.steady?.value, 0),
          safe: readPositiveInteger(inputs.safe?.value, 0),
        };
      }
      const groups = quotaGroupCounts(customQuotaValues());
      const target = currentTargetSizeInput();
      return groupTotal(groups) === target ? groups : scaleGroupsToTotal(groups, target);
    }
    function customGapNumberValues() {
      return {
        challenge: readPositiveInteger(document.querySelector('[data-custom-gap-number="challenge"]')?.value, customGapNumbers.challenge),
        steady: readPositiveInteger(document.querySelector('[data-custom-gap-number="steady"]')?.value, customGapNumbers.steady),
        safe: readPositiveInteger(document.querySelector('[data-custom-gap-number="safe"]')?.value, customGapNumbers.safe),
      };
    }
    function customStrategyGaps() {
      customGapNumbers = customGapNumberValues();
      return {
        challenge: `-${customGapNumbers.challenge}~0分`,
        steady: `0~${customGapNumbers.steady}分`,
        safe: `${customGapNumbers.safe}分以上`,
      };
    }
    function setQuotaInput(name, value) {
      const input = form.elements[name];
      if (input) input.value = String(Math.max(0, Math.floor(Number(value) || 0)));
    }
    function applyCustomGroupCountsToQuotas(syncTarget = false) {
      const groups = customGroupCountValues();
      const total = Math.max(1, groupTotal(groups));
      if (syncTarget && form.elements.targetSize) form.elements.targetSize.value = String(total);
      const challengeParts = distributeCount(groups.challenge, [
        { name: 'customQuotaHighChallenge', weight: strategyBaseQuotas.balanced['高冲'] },
        { name: 'customQuotaChallenge', weight: strategyBaseQuotas.balanced['冲'] },
        { name: 'customQuotaLeanSteady', weight: strategyBaseQuotas.balanced['稳中偏冲'] },
      ]);
      const safeParts = distributeCount(groups.safe, [
        { name: 'customQuotaSafe', weight: strategyBaseQuotas.balanced['保'] },
        { name: 'customQuotaStrongSafe', weight: strategyBaseQuotas.balanced['强保'] },
      ]);
      Object.entries(challengeParts).forEach(([name, value]) => setQuotaInput(name, value));
      setQuotaInput('customQuotaSteady', groups.steady);
      Object.entries(safeParts).forEach(([name, value]) => setQuotaInput(name, value));
      return customQuotaTotal();
    }
    function scaleCustomGroupsToTarget() {
      const scaled = scaleGroupsToTotal(quotaGroupCounts(customQuotaValues()), currentTargetSizeInput());
      setCustomGroupInputs(scaled);
      applyCustomGroupCountsToQuotas(false);
    }
    function setCustomGroupInputs(groups) {
      Object.entries(groups).forEach(([key, value]) => {
        const input = document.querySelector(`[data-custom-count="${key}"]`);
        if (input) input.value = String(Math.max(0, Math.floor(Number(value) || 0)));
      });
    }
    function syncCustomStrategyCardPreview() {
      const card = document.querySelector('.strategy-card[data-strategy-card="custom"]');
      if (!card) return;
      const groups = customGroupCountValues();
      const ratios = ratioPercentagesFromGroups(groups);
      const statValues = card.querySelectorAll('.strategy-card-foot b');
      if (statValues[0]) statValues[0].textContent = fmt(groupTotal(groups));
      if (statValues[1]) statValues[1].textContent = `${fmt((ratios.steady || 0) + (ratios.safe || 0))}%`;
    }
    function currentStrategy() {
      return (form.elements.strategy && form.elements.strategy.value) || 'balanced';
    }
    function syncStrategyDescription() {
      const strategy = currentStrategy();
      const label = strategyLabels[strategy] || strategy;
      const summary = document.getElementById('strategySummaryNote');
      if (summary) summary.textContent = `当前：${label}`;
      const slideSummary = document.getElementById('settingsSlideSummary');
      if (slideSummary && activeSettingsPanel === 'strategy') slideSummary.textContent = `当前：${label}`;
      const description = document.getElementById('strategyDescriptionText');
      if (description) {
        description.textContent = `${strategyDescriptions[strategy] || `当前使用${label}。`} 前三个为预设方案，自定义方案可直接在卡片内调整冲稳保分差说明和志愿数量。`;
      }
      document.querySelectorAll('[data-strategy-choice]').forEach(button => {
        button.classList.toggle('active', button.dataset.strategyChoice === strategy);
      });
    }
    function setStrategy(strategy, dirtyMessage = '已选择新的方案策略，请重新使用生成方案功能') {
      if (!form.elements.strategy || !strategyLabels[strategy]) return;
      const previous = form.elements.strategy.value;
      form.elements.strategy.value = strategy;
      syncCustomPlanPanel();
      renderSelectionCart();
      renderStrategyComparison(latestPlanData);
      if (previous !== strategy) markSettingsDirty(dirtyMessage);
    }
    function syncCustomPlanPanel() {
      if (currentStrategy() === 'custom') applyCustomGroupCountsToQuotas(false);
      if (form.elements.targetSize) form.elements.targetSize.title = '可选择预设，也可直接输入正整数。';
      syncStrategyDescription();
    }
    function targetVolunteerSize() {
      const fromPlan = latestPlanData && latestPlanData.plan && latestPlanData.plan.target_size;
      if (currentStrategy() === 'custom') {
        return Number(customQuotaTotal() || currentTargetSizeInput() || fromPlan || systemRecommendations.length || 96);
      }
      const fromControl = currentTargetSizeInput();
      return Number(fromControl || fromPlan || systemRecommendations.length || 96);
    }
    function recommendationSortWeight(item) {
      const riskIndex = riskOrder.includes(item.risk_band) ? riskOrder.indexOf(item.risk_band) : riskOrder.length;
      const score = Number(item.total_score || 0);
      const rank = item.weighted_reference_rank === null || item.weighted_reference_rank === undefined
        ? Number.MAX_SAFE_INTEGER
        : Number(item.weighted_reference_rank);
      const tags = new Set((item.debug && item.debug.tags) || []);
      const tier = tags.has('985') ? 3 : tags.has('211') ? 2 : tags.has('双一流') ? 1 : 0;
      return { riskIndex, score, rank, tier };
    }
    function isEliteRankMode() {
      const rank = Number((latestPlanData && latestPlanData.candidate && latestPlanData.candidate.rank) || form.elements.rank.value || 0);
      return Number.isFinite(rank) && rank > 0 && rank <= 8000;
    }
    function sortVolunteerRecommendations(items) {
      const eliteMode = isEliteRankMode();
      return items.slice().sort((a, b) => {
        const left = recommendationSortWeight(a);
        const right = recommendationSortWeight(b);
        if (left.riskIndex !== right.riskIndex) return left.riskIndex - right.riskIndex;
        if (eliteMode) {
          if (left.rank !== right.rank) return left.rank - right.rank;
          if (right.tier !== left.tier) return right.tier - left.tier;
        }
        if (right.score !== left.score) return right.score - left.score;
        return left.rank - right.rank;
      });
    }
    function buildAutoSortedRecommendations() {
      const targetSize = targetVolunteerSize();
      const selectedItems = selectedCartItems();
      const requiredSize = Math.max(targetSize, selectedItems.length);
      const merged = [];
      const seen = new Set();
      const add = item => {
        if (!item || seen.has(item.option_key)) return;
        merged.push({ ...item });
        seen.add(item.option_key);
      };
      selectedItems.forEach(add);
      systemRecommendations.forEach(item => {
        if (merged.length < requiredSize) add(item);
      });
      candidateRecommendations.forEach(item => {
        if (merged.length < requiredSize) add(item);
      });
      return sortVolunteerRecommendations(merged);
    }
    function applyLockedPositions(sortedItems) {
      const locked = new Map();
      currentRecommendations.forEach((item, index) => {
        if (item.locked) locked.set(index, item);
      });
      if (!locked.size) return sortedItems;
      const lockedKeys = new Set(Array.from(locked.values()).map(item => item.option_key));
      const unlocked = sortedItems.filter(item => !lockedKeys.has(item.option_key));
      locked.forEach(item => {
        if (!sortedItems.some(option => option.option_key === item.option_key)) unlocked.push(item);
      });
      const total = Math.max(sortedItems.length, currentRecommendations.length);
      const output = [];
      let unlockedIndex = 0;
      for (let index = 0; index < total; index += 1) {
        if (locked.has(index)) output.push({ ...locked.get(index), locked: true });
        else if (unlockedIndex < unlocked.length) output.push({ ...unlocked[unlockedIndex], locked: false });
        unlockedIndex += locked.has(index) ? 0 : 1;
      }
      return output.filter(Boolean);
    }
    function autoSortVolunteers() {
      currentRecommendations = applyLockedPositions(buildAutoSortedRecommendations());
      recommendationPage = 1;
      syncSelectedOrderFromCurrentRecommendations();
      markPlanOrderDirty();
      refreshCurrentPlanViews();
      setActiveStep('2');
    }
    function qs() {
      const data = new FormData(form);
      const params = new URLSearchParams();
      const rank = String(data.get('rank') || '').trim();
      if (!/^[1-9]\d*$/.test(rank)) {
        throw new Error('全省位次必须是正整数。');
      }
      if (selectedSubjects.length !== 3) {
        throw new Error('选科必须且只能选择 3 门。');
      }
      params.set('rank', rank);
      params.set('subjects', selectedSubjects.join(','));
      params.set('interests', splitTerms(data.get('interests') || '').join(','));
      const strategy = currentStrategy();
      const targetSize = String(data.get('targetSize') || '').trim();
      if (!/^[1-9]\d*$/.test(targetSize)) {
        throw new Error('志愿数必须是正整数。');
      }
      if (strategy === 'custom') applyCustomGroupCountsToQuotas(false);
      const quotas = customQuotaValues();
      const customRiskGaps = customGapNumberValues();
      const customTotal = Object.values(quotas).reduce((sum, value) => sum + value, 0);
      params.set('strategy', strategy);
      params.set('custom_quotas', JSON.stringify(quotas));
      params.set('custom_risk_gaps', JSON.stringify(customRiskGaps));
      if (strategy === 'custom') {
        if (customTotal <= 0) throw new Error('自定义方案至少需要设置 1 个志愿数量。');
        params.set('target_size', String(customTotal));
      } else {
        params.set('target_size', targetSize);
      }
      params.set('band_width', data.get('bandWidth') || '20');
      params.set('max_tuition', data.get('maxTuition') || '');
      params.set('preferred_cities', splitTerms(data.get('preferredCities') || '').join(','));
      params.set('blocked_cities', splitTerms(data.get('blockedCities') || '').join(','));
      params.set('avoid_keywords', splitTerms(data.get('avoidKeywords') || '').join(','));
      params.set('priority', data.get('priority') || 'balanced');
      params.set('allow_private', data.get('allowPrivate') ? '1' : '0');
      params.set('allow_sino_foreign', data.get('allowSinoForeign') ? '1' : '0');
      params.set('require_double_first_class', data.get('requireDoubleFirstClass') ? '1' : '0');
      params.set('require_985', data.get('require985') ? '1' : '0');
      params.set('require_211', data.get('require211') ? '1' : '0');
      params.set('require_public_undergraduate', data.get('requirePublicUndergrad') ? '1' : '0');
      return params.toString();
    }
    function setProgress(value, stage, text) {
      progressValue = Math.max(progressValue, value);
      document.getElementById('progressFill').style.width = `${progressValue}%`;
      document.getElementById('progressPercent').textContent = `${progressValue}%`;
      document.getElementById('progressStage').textContent = stage;
      document.getElementById('progressText').textContent = text;
    }
    function showProgress() {
      progressValue = 0;
      progressStartedAt = Date.now();
      document.getElementById('progressOverlay').classList.add('open');
      setProgress(8, '准备中', '正在校验位次、选科和专业选择');
      const stages = [
        [24, '换算位次', '正在查询 2023-2025 一分一段表'],
        [46, '匹配候选', '正在按等效分区间匹配院校专业'],
        [68, '硬性过滤', '正在核对选科和专业选择约束'],
        [86, '风险分层', '正在计算冲稳保和证据链'],
      ];
      let index = 0;
      clearInterval(progressTimer);
      progressTimer = setInterval(() => {
        if (index < stages.length) {
          setProgress(stages[index][0], stages[index][1], stages[index][2]);
          index += 1;
        } else {
          const elapsed = Math.max(1, Math.round((Date.now() - progressStartedAt) / 1000));
          if (progressValue < 98) {
            setProgress(progressValue + 1, '收尾中', `正在整理候选、章程摘要和复核提醒，已用 ${elapsed} 秒`);
          } else {
            setProgress(98, '收尾中', `数据量较大，仍在生成最终表格，已用 ${elapsed} 秒`);
          }
        }
      }, 350);
    }
    function hideProgress(success = true) {
      clearInterval(progressTimer);
      setProgress(success ? 100 : progressValue, success ? '完成' : '未完成', success ? '方案已生成' : '生成失败，请检查提示后重试');
      setTimeout(() => {
        document.getElementById('progressOverlay').classList.remove('open');
      }, 220);
    }
    async function loadPlan(showOverlay = true) {
      if (showOverlay) document.body.classList.add('loading');
      if (showOverlay) showProgress();
      let succeeded = false;
      try {
        const response = await fetch('/plan-data?' + qs());
        if (!response.ok) throw new Error(await response.text());
        render(await response.json());
        planOrderDirty = true;
        clearSettingsDirty();
        succeeded = true;
      } finally {
        if (showOverlay) document.body.classList.remove('loading');
        if (showOverlay) hideProgress(succeeded);
      }
    }
    function renderSubjectDialog() {
      const grid = document.getElementById('subjectGrid');
      grid.innerHTML = subjectOptions.map(subject => {
        const checked = selectedSubjects.includes(subject);
        return `<label class="subject-option ${checked ? 'selected' : ''}">
          <input type="checkbox" value="${subject}" ${checked ? 'checked' : ''}>
          <span>${subject}</span>
        </label>`;
      }).join('');
      grid.querySelectorAll('input[type="checkbox"]').forEach(input => {
        input.addEventListener('change', () => {
          const value = input.value;
          if (input.checked) {
            if (selectedSubjects.length >= 3) {
              input.checked = false;
              document.getElementById('subjectError').textContent = '只能选择 3 门选科。';
              return;
            }
            selectedSubjects.push(value);
          } else {
            selectedSubjects = selectedSubjects.filter(item => item !== value);
          }
          document.getElementById('subjectError').textContent = selectedSubjects.length === 3 ? '' : `还需要选择 ${3 - selectedSubjects.length} 门。`;
          renderSubjectDialog();
          syncSubjects();
          markSettingsDirty();
        });
      });
    }
    function syncSubjects() {
      document.getElementById('subjectsValue').value = selectedSubjects.join(',');
      document.getElementById('subjectButton').textContent = selectedSubjects.length ? selectedSubjects.join('、') : '请选择 3 门';
    }
    function openSubjectDialog() {
      renderSubjectDialog();
      document.getElementById('subjectDialog').classList.add('open');
    }
    function markSettingsDirty(message = '已修改设置，请重新生成志愿方案') {
      settingsDirty = true;
      form.classList.add('has-dirty-note');
      document.getElementById('settingsDirtyBanner').textContent = message;
      document.getElementById('settingsDirtyBanner').classList.add('open');
    }
    function clearSettingsDirty() {
      settingsDirty = false;
      form.classList.remove('has-dirty-note');
      document.getElementById('settingsDirtyBanner').textContent = '';
      document.getElementById('settingsDirtyBanner').classList.remove('open');
    }
    function syncInterests() {
      document.getElementById('interestsValue').value = selectedInterests.join(',');
      const button = document.getElementById('interestPickerButton');
      button.innerHTML = selectedInterests.length
        ? selectedInterests.slice(0, 3).map(item => `<span class="tag-chip">${item}</span>`).join('') +
          (selectedInterests.length > 3 ? `<span class="tag-chip">+${selectedInterests.length - 3}</span>` : '')
        : '<span class="tag-placeholder">不限专业选择（全部）</span>';
      document.getElementById('interestCount').textContent = selectedInterests.length
        ? `已选 ${selectedInterests.length} 项`
        : '不限专业选择 · 默认全部';
    }
    function allInterestItems() {
      return majorSelectionItems().map(item => item.name);
    }
    function setActiveStep(step) {
      const targetStep = document.querySelector(`[data-step-panel="${step}"]`) ? step : '2';
      document.querySelectorAll('[data-step-tab]').forEach(button => {
        const active = button.dataset.stepTab === targetStep;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      document.querySelectorAll('[data-step-panel]').forEach(panel => {
        panel.hidden = panel.dataset.stepPanel !== targetStep;
      });
    }
    function setSelectedInterests(items) {
      const allowed = new Set(allInterestItems());
      const next = [];
      items.forEach(item => {
        const value = String(item || '').trim();
        if (!value) return;
        if (allowed.has(value)) {
          next.push(value);
          return;
        }
        selectionNamesForKeyword(value).forEach(name => next.push(name));
      });
      selectedInterests = Array.from(new Set(next));
      syncInterests();
      renderInterestOptions();
      renderMajorSelector();
    }
    function renderInterestOptions() {
      const query = document.getElementById('interestSearch').value.trim();
      const normalizedTerms = normalizeMajorSearchText(query)
        .split(/[,\s，、;；/]+/)
        .map(item => item.trim())
        .filter(Boolean);
      const selected = new Set(selectedInterests);
      let items = majorSelectionItems().filter(item => {
        if (!normalizedTerms.length) return item.kind === 'standard' || selected.has(item.name);
        return normalizedTerms.every(term => item.searchText.includes(term));
      });
      if (!majorCatalog.length && !admissionMajorCatalog.length) {
        document.getElementById('interestOptionList').innerHTML = '<div class="mini">专业目录正在加载，请稍候。</div>';
        return;
      }
      items = items.slice(0, normalizedTerms.length ? 360 : 1200);
      const grouped = new Map();
      items.forEach(item => {
        const group = item.kind === 'admission' ? '山东发布招生专业名称' : item.group;
        if (!grouped.has(group)) grouped.set(group, []);
        grouped.get(group).push(item);
      });
      const html = Array.from(grouped.entries()).map(([group, groupItems]) => {
        return `<section class="tag-group">
          <h3>${escapeHtml(group)} <span class="mini">${fmt(groupItems.length)} 项</span></h3>
          <div class="tag-options">
            ${groupItems.map(item => `<button type="button" class="tag-option ${selected.has(item.name) ? 'selected' : ''}" data-interest="${escapeHtml(item.name)}">
              <span class="tag-main"><b>${escapeHtml(item.name)}</b><small>${escapeHtml(item.displayMeta)}</small></span>
              <span class="tag-source-badge ${item.kind === 'admission' ? 'admission' : ''}">${escapeHtml(item.badge)}</span>
            </button>`).join('')}
          </div>
        </section>`;
      }).join('');
      document.getElementById('interestOptionList').innerHTML = html || '<div class="mini">没有匹配的专业，请换一个关键词搜索。</div>';
      document.querySelectorAll('.tag-option').forEach(button => {
        button.addEventListener('click', () => {
          const value = button.dataset.interest;
          if (selectedInterests.includes(value)) {
            selectedInterests = selectedInterests.filter(item => item !== value);
          } else {
            selectedInterests.push(value);
          }
          document.getElementById('interestPickerError').textContent = '';
          syncInterests();
          renderInterestOptions();
          renderMajorSelector();
          markSettingsDirty();
        });
      });
    }
    function openInterestPickerDialog() {
      document.getElementById('interestPickerError').textContent = '';
      document.getElementById('interestSearch').value = '';
      syncInterests();
      renderInterestOptions();
      document.getElementById('interestPickerDialog').classList.add('open');
      document.getElementById('interestSearch').focus();
    }
    function closeInterestPickerDialog() {
      document.getElementById('interestPickerDialog').classList.remove('open');
    }
    function renderInterestQuestions() {
      document.getElementById('interestQuestions').innerHTML = interestQuestions.map((question, index) => {
        const active = interestAnswers[question.id];
        return `<div class="question">
          <p>${index + 1}. ${question.text}</p>
          <div class="scale" data-question="${question.id}">
            ${[1, 2, 3, 4, 5].map(value => `<button type="button" data-value="${value}" class="${active === value ? 'active' : ''}">${value}</button>`).join('')}
          </div>
          <div class="mini">1 完全不像我 · 3 说不准 · 5 非常像我</div>
        </div>`;
      }).join('');
      document.querySelectorAll('.scale button').forEach(button => {
        button.addEventListener('click', () => {
          const questionId = button.parentElement.dataset.question;
          interestAnswers[questionId] = Number(button.dataset.value);
          document.getElementById('interestError').textContent = '';
          renderInterestQuestions();
        });
      });
    }
    function openInterestDialog() {
      renderInterestQuestions();
      document.getElementById('interestDialog').classList.add('open');
    }
    function closeInterestDialog() {
      document.getElementById('interestDialog').classList.remove('open');
    }
    function calculateInterestResult() {
      if (Object.keys(interestAnswers).length !== interestQuestions.length) {
        document.getElementById('interestError').textContent = `还有 ${interestQuestions.length - Object.keys(interestAnswers).length} 题未完成。`;
        return;
      }
      const scores = { R: 0, I: 0, A: 0, S: 0, E: 0, C: 0 };
      interestQuestions.forEach(question => {
        scores[question.type] += interestAnswers[question.id] || 0;
      });
      const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]);
      const topScore = ranked[0][1];
      const selectedTypes = ranked.filter(([, score], index) => index < 2 || topScore - score <= 2).slice(0, 3).map(([type]) => type);
      generatedInterestKeywords = Array.from(new Set(selectedTypes.flatMap(type => interestKeywordMap[type])));
      const recommendedSelections = Array.from(new Set(
        generatedInterestKeywords.flatMap(keyword => selectionNamesForKeyword(keyword, 6))
      )).slice(0, 18);
      const differentiation = ranked[0][1] - ranked[ranked.length - 1][1];
      const note = differentiation <= 5
        ? '兴趣分化不明显，建议保留多个方向，并结合学科优势继续筛选。'
        : '兴趣分化较清晰，可优先围绕前两个方向筛选专业。';
      document.getElementById('interestResult').classList.add('open');
      document.getElementById('interestResult').innerHTML = `
        <h3>测试结果</h3>
        <div class="mini">RIASEC 得分：${ranked.map(([type, score]) => `${interestTypeLabels[type]} ${score}`).join(' / ')}</div>
        <p><b>主导兴趣：</b>${selectedTypes.map(type => interestTypeLabels[type]).join('、')}</p>
        <p><b>建议专业选择：</b>${(recommendedSelections.length ? recommendedSelections : generatedInterestKeywords).join('、')}</p>
        <p class="mini">${note}</p>`;
    }
    function closeSubjectDialog() {
      document.getElementById('subjectDialog').classList.remove('open');
    }
    function render(data) {
      latestPlanData = data;
      if (data.system_info) {
        systemInfo = {
          ...data.system_info,
          official_2026_status: data.official_2026_status || data.system_info.official_2026_status || (systemInfo && systemInfo.official_2026_status),
        };
        refreshSystemInfoUI();
      }
      const p = data.plan;
      const rank = fmt(data.candidate.rank);
      const conversionTitle = document.getElementById('conversionTitle');
      if (conversionTitle) conversionTitle.textContent = `2026 位次 ${rank} 的后台等效分计算`;
      renderEquivalentRows(data.equivalent_scores);
      renderBandRows(data.band_matches);
      renderRightRail(p, data);
      candidateRecommendations = uniqueByOptionKey((p.candidate_recommendations || p.recommendations).map(item => ({ ...item })));
      searchRecommendations = uniqueByOptionKey((p.search_recommendations || p.candidate_recommendations || p.recommendations).map(item => ({ ...item })));
      systemRecommendations = uniqueByOptionKey(p.recommendations.map(item => ({ ...item })));
      selectedOptionKeys = new Set([...selectedOptionKeys].filter(key => searchRecommendations.some(item => item.option_key === key)));
      normalizeSelectedOrder();
      invalidateReportCache();
      currentRecommendations = selectedOptionKeys.size
        ? selectedCartItems().map(item => ({ ...item }))
        : systemRecommendations.map(item => ({ ...item }));
      candidateSearchText = '';
      candidateRiskFilter = 'all';
      const candidateSearchInput = document.getElementById('candidateSearch');
      if (candidateSearchInput) candidateSearchInput.value = '';
      matchedPage = 1;
      recommendationPage = 1;
      renderMajorSelector();
      renderStrategyComparison(data);
      renderMatchedUniversityRows();
      renderInterestPreview();
      renderSortRows();
      renderSelectionCart();
    }
    function renderEquivalentRows(items) {
      const target = document.getElementById('equivalentRows');
      if (!target) return;
      target.innerHTML = items.map((item, index) =>
        `<tr>
          <td>${item.year}${index === 0 ? ' <span class="school-tag elite">最新</span>' : ''}</td>
          <td>${calcValue(fmt(item.rank), '这里用的是你输入的 2026 全省位次。系统拿这个名次去查往年一分一段表。')}</td>
          <td><b>${calcValue(`${item.score} 分`, `${item.year} 年大约排到这个名次时，对应的是多少分。报志愿时应拿这个等效分去参考当年的录取线。`)}</b></td>
          <td>${calcValue(fmt(item.cumulative_count), `${item.year} 年这个分数及以上一共有多少人。这个数应当刚好覆盖你的名次，用来检查查表是否靠谱。`)}</td>
          <td>${item.source_id}</td>
          <td>${equivalentSparkline(items, index)}</td>
        </tr>`
      ).join('');
    }
    function renderBandRows(items) {
      const target = document.getElementById('bandRows');
      if (!target) return;
      target.innerHTML = items.map(item =>
        `<tr>
          <td>${item.year}</td>
          <td>${calcValue(item.center_score, `${item.year} 年同名次大约对应的分数。`)}</td>
          <td>${calcValue(`${item.low_score}-${item.high_score}`, `系统会先看这个分数范围内，往年有哪些学校专业可以选。`)}</td>
          <td>${calcValue(fmt(item.matched_records), `往年投档表中，落在这个分数范围里的原始记录数量。`)}</td>
          <td>${calcValue(fmt(item.matched_options), `去掉重复后，大约有多少个学校专业可作为候选。`)}</td>
        </tr>`
      ).join('');
    }
    function renderRightRail(plan, data) {
      renderSelectionCart();
    }
    function renderStrategyComparison(data = null) {
      const target = document.getElementById('strategyCompareCards');
      if (!target) return;
      const compare = (data && data.strategy_compare) || {};
      const generatedStrategy = data && data.plan ? data.plan.strategy : '';
      const selectedStrategy = currentStrategy() || generatedStrategy || 'balanced';
      const order = strategyCompareOrder;
      target.innerHTML = order.map(key => {
        const item = compare[key] || null;
        const groups = strategyGroupCounts(key, item);
        const total = groupTotal(groups) || (item ? item.total || 0 : 0);
        const ratios = strategyRatioPercentages(key, item);
        const stable = item ? (item.stable_ratio || 0) : ratios.steady + ratios.safe;
        const active = key === selectedStrategy;
        const pendingText = active && generatedStrategy && key !== generatedStrategy ? '<div class="mini" style="color:#c74747;">已选择，需点击生成方案后生效。</div>' : '';
        const gaps = key === 'custom' ? customStrategyGaps() : strategyGapSettings[key];
        const groupRows = [
          ['challenge', '冲'],
          ['steady', '稳'],
          ['safe', '保'],
        ].map(([groupKey, label]) => {
          const gap = gaps[groupKey] || '';
          const count = Math.max(0, Number(groups[groupKey]) || 0);
          const customGapInput = `<input type="number" min="0" step="1" value="${customGapNumbers[groupKey]}" data-custom-gap-number="${groupKey}" aria-label="自定义${label}分差数值">`;
          const customGapRange = {
            challenge: `<label class="strategy-gap-range"><span>-</span>${customGapInput}<span>分 ~ 0分</span></label>`,
            steady: `<label class="strategy-gap-range"><span>0分 ~</span>${customGapInput}<span>分</span></label>`,
            safe: `<label class="strategy-gap-range safe">${customGapInput}<span>分及以上</span></label>`,
          }[groupKey] || `<label class="strategy-gap-range">${customGapInput}<span>分</span></label>`;
          const gapCell = key === 'custom'
            ? customGapRange
            : `<span class="strategy-readonly-value">${escapeHtml(gap)}</span>`;
          const countCell = key === 'custom'
            ? `<input type="number" min="0" step="1" value="${count}" data-custom-count="${groupKey}" aria-label="自定义${label}志愿数量">`
            : `<span class="strategy-readonly-value">${fmt(count)} 个</span>`;
          return `
            <div class="strategy-setting-cell strategy-band-label">${label}</div>
            <div class="strategy-setting-cell">${gapCell}</div>
            <div class="strategy-setting-cell">${countCell}</div>`;
        }).join('');
        const help = '这张卡是在比较不同填报策略。志愿数表示这套方案放了多少条；稳保比例越高，方案越保守。自定义方案中的分差用数字输入，系统会自动换算为冲、稳、保区间。';
        return `<article class="compare-card strategy-card ${active ? 'active' : ''}" data-strategy-card="${key}" role="button" tabindex="0" aria-pressed="${active ? 'true' : 'false'}" title="${help}">
          <div class="strategy-card-head">
            <h3>${strategyLabels[key] || key}</h3>
            <span class="strategy-select-chip">${active ? '已选' : '点击选择'}</span>
          </div>
          <div class="strategy-setting-grid" aria-label="${strategyLabels[key] || key}冲稳保设定">
            <div class="strategy-setting-cell strategy-setting-head">档位</div>
            <div class="strategy-setting-cell strategy-setting-head">分差设定</div>
            <div class="strategy-setting-cell strategy-setting-head">志愿数量</div>
            ${groupRows}
          </div>
          <div class="strategy-card-foot">
            <span><b>${fmt(total)}</b>合计</span>
            <span><b>${fmt(stable)}%</b>稳保比例</span>
          </div>
          ${pendingText}
        </article>`;
      }).join('');
    }
    function charterRiskItems(recommendations) {
      const subjectCount = recommendations.filter(item => item.debug && item.debug.subjects && item.debug.subjects.length && !item.debug.subjects.includes('不限')).length;
      const warningCount = recommendations.filter(item => item.warnings && item.warnings.length).length;
      const planUnknownCount = recommendations.filter(item => !item.debug || item.debug.plan_count_2026 === null || item.debug.plan_count_2026 === undefined).length;
      const singleYearCount = recommendations.filter(item => (item.evidence || []).filter(e => e.min_rank !== null && e.min_rank !== undefined).length === 1).length;
      const charterRiskCount = recommendations.filter(item => item.debug && item.debug.charter_risks && item.debug.charter_risks.length).length;
      const highCharterCount = recommendations.filter(item => item.debug && item.debug.charter_level === 'high').length;
      return [
        { label: '章程规则命中风险', count: charterRiskCount },
        { label: '高风险章程项', count: highCharterCount },
        { label: '单年样本，历史证据不足', count: singleYearCount },
        { label: '需核对专业选科与体检限制', count: subjectCount },
        { label: '近年趋势或计划波动提醒', count: warningCount },
        { label: '2026 招生计划待人工确认', count: planUnknownCount },
      ];
    }
    function recommendationExplanation(item) {
      const risk = item.rank_margin === null || item.rank_margin === undefined
        ? '历史位次证据不足'
        : item.rank_margin >= 0
          ? `参考位次比当前位次安全 ${fmt(item.rank_margin)} 位`
          : `参考位次比当前位次高 ${fmt(Math.abs(item.rank_margin))} 位`;
      const fit = item.fit_score >= 0.65 ? '专业匹配较强' : item.fit_score >= 0.50 ? '专业有一定相关性' : '主要依赖位次安全性';
      return `${risk}；${fit}；稳定性 ${Math.round(item.stability_score * 100)}%。`;
    }
    function planChangeText(item) {
      const latest = item.evidence[item.evidence.length - 1];
      const historicalPlans = item.evidence.map(e => `${e.year}:${fmt(e.plan_count)}`).join(' / ');
      const plan2026 = item.debug && item.debug.plan_count_2026;
      const plan2026Status = item.debug && item.debug.plan_count_2026_status;
      const planEstimate = item.debug && item.debug.plan_count_2026_estimated;
      if (plan2026Status === 'stopped') {
        return '2026官方补充信息：该专业停止招生';
      }
      if (plan2026 === null || plan2026 === undefined) {
        if (planEstimate) {
          return `2026计划：官方分专业计划待导入；历史估算约 ${fmt(planEstimate)} 人；历史计划 ${historicalPlans || '待接入'}`;
        }
        return `2026 计划：待导入官方招生计划；历史计划 ${historicalPlans || '待接入'}`;
      }
      const diff = latest && latest.plan_count ? plan2026 - latest.plan_count : null;
      const label = plan2026Status === 'official_supplement'
        ? '2026 官方补充调整'
        : plan2026Status && plan2026Status !== 'official'
          ? '2026 计划参考'
          : '2026 计划';
      return `${label} ${fmt(plan2026)}；较最新历史计划 ${diff === null ? '待比较' : diff >= 0 ? `增加 ${fmt(diff)}` : `减少 ${fmt(Math.abs(diff))}`}`;
    }
    function schoolTagHtml(tags) {
      return tags.map(tag => {
        const elite = ['985', '211', '双一流'].includes(tag);
        return `<span class="school-tag ${elite ? 'elite' : ''}">${escapeHtml(tag)}</span>`;
      }).join('');
    }
    function optionMetaChipHtml(text, important = false) {
      if (!text) return '';
      return `<span class="option-meta-chip ${important ? 'important' : ''}">${escapeHtml(text)}</span>`;
    }
    function optionProjectTagHtml(text) {
      if (!text) return '';
      return `<span class="option-project-tag">${escapeHtml(text)}</span>`;
    }
    function optionSummaryHtml(item) {
      const meta = schoolMeta(item);
      const codes = optionCodes(item);
      const debug = item.debug || {};
      const identity = debug.identity || {};
      const subjects = identity.subjects && identity.subjects.length ? `选科 ${identity.subjects.join('/')}` : '';
      const chips = [
        optionMetaChipHtml(identity.campus ? `校区 ${identity.campus}` : ''),
        optionMetaChipHtml(subjects),
        optionMetaChipHtml(identity.tuition ? `学费 ${fmt(identity.tuition)}` : ''),
      ].filter(Boolean).join('');
      const projectTags = optionProjectTags(item).map(optionProjectTagHtml).join('');
      return `<div class="school-cell">
        <div class="option-primary">
          <div class="school-name-line">
            <span class="option-code">${escapeHtml(codes.schoolCode)} / ${escapeHtml(codes.majorCode)}</span>
            <span class="school-name">${escapeHtml(meta.school)}</span>
          </div>
          <div class="major-name">${escapeHtml(optionMajor(item))}</div>
        </div>
        ${chips ? `<div class="option-meta-row">${chips}</div>` : ''}
        ${projectTags ? `<div class="option-tag-row">${projectTags}</div>` : ''}
      </div>`;
    }
    function schoolLevelCellHtml(item) {
      const tags = schoolLevelTags(item);
      return `<div class="school-tags level-tags">${tags.length ? schoolTagHtml(tags) : '<span class="school-tag">本科</span>'}</div>`;
    }
    function schoolLevelText(tags) {
      if (tags.includes('985')) return '985 本科';
      if (tags.includes('211')) return '211 本科';
      if (tags.includes('双一流')) return '双一流本科';
      return '本科';
    }
    function renderMatchedUniversityRows() {
      const rows = filteredCandidateRecommendations();
      const page = pageWindow(rows, matchedPage);
      matchedPage = page.current;
      const freePool = searchRecommendations.length ? searchRecommendations : candidateRecommendations;
      const baseRows = (
        freeSelectionMode
          ? freePool
          : (candidateSearchText.trim() ? candidateRecommendations : candidateRecommendations.filter(candidateMatchesSelectedMajors))
      ).filter(candidateMatchesSearch);
      const countsByRisk = rows.reduce((acc, item) => {
        acc[item.risk_band] = (acc[item.risk_band] || 0) + 1;
        return acc;
      }, {});
      const baseCounts = baseRows.reduce((acc, item) => {
        acc[item.risk_band] = (acc[item.risk_band] || 0) + 1;
        return acc;
      }, {});
      const counts = riskGroupCounts(countsByRisk);
      const allGroups = riskGroupCounts(baseCounts);
      const activeRiskFilter = freeSelectionMode && candidateRiskFilter !== 'selected' ? 'all' : candidateRiskFilter;
      document.getElementById('matchedFilters').innerHTML = [
        ['all', `全部 ${fmt(baseRows.length)} 项`],
        ['challenge', `冲 ${fmt(allGroups.challenge)} 所`],
        ['steady', `稳 ${fmt(allGroups.steady)} 所`],
        ['safe', `保 ${fmt(allGroups.safe)} 所`],
      ].map(([key, text]) => `<button type="button" class="filter-pill ${activeRiskFilter === key ? 'active' : ''}" data-risk-filter="${key}">${text}</button>`).join('');
      const tableRows = page.items.map((item, index) => {
        const meta = schoolMeta(item);
        const percent = matchPercent(item);
        const successColor = successRateColor(percent);
        const checked = selectedOptionKeys.has(item.option_key);
        const actionButton = candidateRiskFilter === 'selected'
          ? `<button type="button" class="secondary-button danger-text-button" data-action="remove-selected" data-option-key="${item.option_key}">移除</button>`
          : `<button type="button" class="secondary-button ${checked ? 'is-selected' : ''}" data-action="toggle-selected" data-option-key="${item.option_key}">${checked ? '已加入' : '加入'}</button>`;
        return `<tr>
          <td>
            ${optionSummaryHtml(item)}
          </td>
          <td>${schoolLevelCellHtml(item)}</td>
          <td>${disciplineAssessmentHtml(item)}</td>
          <td>${meta.city}</td>
          <td>${planCount2026Html(item)}</td>
          <td>${admissionHistoryHtml(item)}</td>
          <td><div class="match-column"><div class="match-meter" title="${escapeHtml(matchPercentHelp(item))}"><div class="track"><div class="fill" style="width:${percent}%; background:${successColor};"></div></div><b class="success-rate-text" style="color:${successColor};">${percent}%</b></div>${charterCompactHtml(item, 2)}</div></td>
          <td><span class="risk-badge ${riskClass(item.risk_band)}">${item.risk_band}</span></td>
          <td><div class="candidate-actions">${charterActionLinkHtml(item)}${actionButton}</div></td>
        </tr>`;
      }).join('');
      document.getElementById('matchedUniversityRows').innerHTML = tableRows || `<tr><td colspan="9" class="empty-row">${matchedEmptyMessage()}</td></tr>`;
      renderPagination('matchedPagination', 'matched', page.current, rows.length);
    }
    function renderInterestPreview() {
    }
    function sortLaneMeta(group) {
      return {
        challenge: { title: '冲刺区', sub: '按意愿与可冲价值排序，保留明确想冲的目标。' },
        steady: { title: '稳妥区', sub: '优先专业匹配、位次余量和计划稳定性。' },
        safe: { title: '保底区', sub: '确保兜底梯度充足，避免全部过于集中。' },
        unknown: { title: '待复核区', sub: '证据不足或规则不完整，正式填报前重点核验。' },
      }[group] || { title: group, sub: '需要人工复核。' };
    }
    function sortLaneOrder(items) {
      const groups = ['challenge', 'steady', 'safe'];
      if (items.some(item => cartRiskGroup(item) === 'unknown')) groups.push('unknown');
      return groups;
    }
    function sortGroupIndexes(group) {
      return currentRecommendations
        .map((item, index) => cartRiskGroup(item) === group ? index : -1)
        .filter(index => index >= 0);
    }
    function sortSummaryHtml() {
      const counts = currentRecommendations.reduce((acc, item) => {
        const group = cartRiskGroup(item);
        acc[group] = (acc[group] || 0) + 1;
        return acc;
      }, {});
      const locked = currentRecommendations.filter(item => item.locked).length;
      const charterRisk = currentRecommendations.filter(item => (charterInfo(item).rules || []).length).length;
      return `<div class="sort-smart-strip">
        <div class="sort-smart-card"><b>${fmt(currentRecommendations.length)}</b><span>当前志愿总数</span></div>
        <div class="sort-smart-card"><b>${fmt(counts.challenge || 0)}</b><span>冲刺区</span></div>
        <div class="sort-smart-card"><b>${fmt(counts.steady || 0)} / ${fmt(counts.safe || 0)}</b><span>稳妥 / 保底</span></div>
        <div class="sort-smart-card"><b>${fmt(locked)} / ${fmt(charterRisk)}</b><span>锁定 / 章程风险</span></div>
      </div>`;
    }
    function sortCardHtml(item, globalIndex) {
        const meta = schoolMeta(item);
        const quality = evidenceQuality(item);
        const evidence = item.evidence.map(e => `<li>${e.year}：最低位次 ${fmt(e.min_rank)}，计划 ${fmt(e.plan_count)}，来源 ${e.source_id}</li>`).join('');
        const tests = item.falsification_tests.map(t => `<li>${t}</li>`).join('');
        const warnings = item.warnings.length ? `<div class="mini">提醒：${item.warnings.join('；')}</div>` : '';
        const planChange = planChangeText(item);
        const reasonGroups = splitRecommendationReasons(item);
        const otherReason = reasonGroups.other[0] || recommendationExplanation(item);
      return `<article class="sort-card" draggable="${item.locked ? 'false' : 'true'}" data-index="${globalIndex}" data-risk-group="${cartRiskGroup(item)}">
        <div class="sort-card-top">
          <span class="sort-seq">${fmt(globalIndex + 1)}</span>
          <div class="sort-card-title">
            <b>${escapeHtml(meta.school)} / ${escapeHtml(optionMajor(item))}</b>
            <span class="mini">${escapeHtml(meta.city)} · ${escapeHtml(optionIdentity(item))}</span>
            ${meta.tags.length ? `<div class="school-tags">${schoolTagHtml(meta.tags)}</div>` : ''}
          </div>
        </div>
        <div class="sort-card-facts">
          <div class="sort-fact left-fact"><b>参考位次</b><span>${fmt(item.weighted_reference_rank)} · 差值 ${fmt(item.rank_margin)} · ${escapeHtml(item.trend || '趋势待接入')}</span><span class="evidence-badge ${quality.cls}">${quality.label}</span>${evidenceSampleNote(item)}</div>
          <div class="sort-fact left-fact"><b>章程核验</b><span>${charterCompactHtml(item, 3)}</span></div>
          <div class="sort-fact left-fact"><b>匹配专业</b>${compactTagHtml(reasonGroups.interests, '未直接命中专业选择')}</div>
          <div class="sort-card-risk-column"><b>冲稳保</b><span class="risk-badge ${riskClass(item.risk_band)}">${item.risk_band}</span></div>
          <div class="sort-fact right-fact"><b>相关专业组</b>${compactTagHtml(reasonGroups.related, '无额外相关专业组')}</div>
          <div class="sort-fact right-fact"><b>位次/计划</b><span>${escapeHtml(otherReason)}；${escapeHtml(planChange)}</span></div>
          <div class="sort-fact right-fact"><b>专业提醒</b><span>${escapeHtml(majorKnowledgeText(item))}</span></div>
        </div>
        ${warnings}
        <details class="compact-details">
          <summary>展开历史依据和推翻条件</summary>
          <ul>${evidence}</ul>
          <div class="mini" style="margin-top:8px;">什么情况下要推翻这个推荐</div>
          <ul>${tests}</ul>
        </details>
        ${item.locked ? '<span class="lock-badge">已锁定，拖拽前请先解锁</span>' : ''}
        ${sortActionHtml(item, globalIndex)}
      </article>`;
    }
    function renderRecommendationRows() {
      const target = document.getElementById('recommendationRows');
      if (!target) return;
      if (!currentRecommendations.length) {
        target.innerHTML = '<div class="sort-empty">当前还没有候选。请先在选择学校专业中加入清单。</div>';
        return;
      }
      const lanes = sortLaneOrder(currentRecommendations).map(group => {
        const meta = sortLaneMeta(group);
        const indexes = sortGroupIndexes(group);
        const cards = indexes.map(index => sortCardHtml(currentRecommendations[index], index)).join('');
        return `<section class="sort-lane" data-risk-group="${group}">
          <div class="sort-lane-head">
            <div><b>${meta.title}</b><span>${meta.sub}</span></div>
            <span class="sort-lane-count">${fmt(indexes.length)}</span>
          </div>
          <div class="sort-card-list">
            ${cards || '<div class="sort-empty">这一组暂无志愿。</div>'}
          </div>
        </section>`;
      }).join('');
      target.innerHTML = `${sortSummaryHtml()}<div class="sort-board">${lanes}</div>`;
    }
    function renderSortRows() {
      renderRecommendationRows();
      const pagination = document.getElementById('recommendationPagination');
      if (pagination) {
        pagination.innerHTML = currentRecommendations.length
          ? `<span>共 ${fmt(currentRecommendations.length)} 个志愿 · 按冲稳保分区展示，可拖动卡片调整组内顺序</span>`
          : '';
      }
      renderPlanSaveStatus();
    }
    function moveRecommendation(index, direction) {
      if (!currentRecommendations[index]) return;
      if (currentRecommendations[index].locked) {
        alert('该志愿已锁定，需先解锁后再移动。');
        return;
      }
      let target = index + direction;
      while (target >= 0 && target < currentRecommendations.length && currentRecommendations[target].locked) {
        target += direction;
      }
      if (target < 0 || target >= currentRecommendations.length) return;
      const next = currentRecommendations.slice();
      [next[index], next[target]] = [next[target], next[index]];
      currentRecommendations = next;
      recommendationPage = Math.floor(target / currentPageSize()) + 1;
      syncSelectedOrderFromCurrentRecommendations();
      markPlanOrderDirty();
      refreshCurrentPlanViews();
    }
    function moveRecommendationTo(index, targetPosition) {
      if (!currentRecommendations[index]) return;
      if (currentRecommendations[index].locked) {
        alert('该志愿已锁定，需先解锁后再移动。');
        return;
      }
      const targetIndex = Math.max(0, Math.min(currentRecommendations.length - 1, targetPosition - 1));
      const locked = new Map();
      currentRecommendations.forEach((item, itemIndex) => {
        if (item.locked) locked.set(itemIndex, item);
      });
      const slots = [];
      for (let slot = 0; slot < currentRecommendations.length; slot += 1) {
        if (!locked.has(slot)) slots.push(slot);
      }
      const fromSlot = slots.indexOf(index);
      if (fromSlot < 0) return;
      let toSlot = slots.findIndex(slot => slot >= targetIndex);
      if (toSlot < 0) toSlot = slots.length - 1;
      const unlocked = currentRecommendations.filter(item => !item.locked);
      const [moved] = unlocked.splice(fromSlot, 1);
      unlocked.splice(toSlot, 0, moved);
      const next = [];
      let unlockedIndex = 0;
      for (let itemIndex = 0; itemIndex < currentRecommendations.length; itemIndex += 1) {
        if (locked.has(itemIndex)) next.push(locked.get(itemIndex));
        else {
          next.push(unlocked[unlockedIndex]);
          unlockedIndex += 1;
        }
      }
      currentRecommendations = next;
      recommendationPage = Math.floor(targetIndex / currentPageSize()) + 1;
      syncSelectedOrderFromCurrentRecommendations();
      markPlanOrderDirty();
      refreshCurrentPlanViews();
    }
    function clearSortDropState() {
      document.querySelectorAll('.sort-lane.drop-active').forEach(lane => lane.classList.remove('drop-active'));
      document.querySelectorAll('.sort-card.dragging').forEach(card => card.classList.remove('dragging'));
    }
    function handleRecommendationDragStart(event) {
      const card = event.target.closest('.sort-card[data-index]');
      if (!card) return;
      const index = Number(card.dataset.index);
      if (!Number.isInteger(index) || !currentRecommendations[index]) return;
      if (currentRecommendations[index].locked) {
        event.preventDefault();
        alert('该志愿已锁定，需先解锁后再拖动。');
        return;
      }
      draggedRecommendationIndex = index;
      card.classList.add('dragging');
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', String(index));
      }
    }
    function handleRecommendationDragOver(event) {
      const lane = event.target.closest('.sort-lane[data-risk-group]');
      if (!lane || draggedRecommendationIndex === null || !currentRecommendations[draggedRecommendationIndex]) return;
      const draggedGroup = cartRiskGroup(currentRecommendations[draggedRecommendationIndex]);
      if (lane.dataset.riskGroup !== draggedGroup) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
      document.querySelectorAll('.sort-lane.drop-active').forEach(item => {
        if (item !== lane) item.classList.remove('drop-active');
      });
      lane.classList.add('drop-active');
    }
    function handleRecommendationDrop(event) {
      const lane = event.target.closest('.sort-lane[data-risk-group]');
      if (!lane || draggedRecommendationIndex === null || !currentRecommendations[draggedRecommendationIndex]) return;
      const draggedGroup = cartRiskGroup(currentRecommendations[draggedRecommendationIndex]);
      if (lane.dataset.riskGroup !== draggedGroup) return;
      event.preventDefault();
      const targetCard = event.target.closest('.sort-card[data-index]');
      const groupIndexes = sortGroupIndexes(draggedGroup);
      let targetIndex = targetCard ? Number(targetCard.dataset.index) : (groupIndexes.length ? groupIndexes[groupIndexes.length - 1] : draggedRecommendationIndex);
      if (!Number.isInteger(targetIndex)) targetIndex = draggedRecommendationIndex;
      if (targetIndex !== draggedRecommendationIndex) {
        moveRecommendationTo(draggedRecommendationIndex, targetIndex + 1);
      }
      draggedRecommendationIndex = null;
      clearSortDropState();
    }
    function handleRecommendationDragEnd() {
      draggedRecommendationIndex = null;
      clearSortDropState();
    }
    function sortDropTargetFromPoint(clientX, clientY) {
      const element = document.elementFromPoint(clientX, clientY);
      if (!element) return null;
      const lane = element.closest('.sort-lane[data-risk-group]');
      if (!lane) return null;
      const targetCard = element.closest('.sort-card[data-index]');
      return { lane, targetCard };
    }
    function applySortDrop(fromIndex, lane, targetCard) {
      if (!currentRecommendations[fromIndex] || !lane) return false;
      const draggedGroup = cartRiskGroup(currentRecommendations[fromIndex]);
      if (lane.dataset.riskGroup !== draggedGroup) return false;
      const groupIndexes = sortGroupIndexes(draggedGroup);
      let targetIndex = targetCard ? Number(targetCard.dataset.index) : (groupIndexes.length ? groupIndexes[groupIndexes.length - 1] : fromIndex);
      if (!Number.isInteger(targetIndex) || targetIndex === fromIndex) return false;
      moveRecommendationTo(fromIndex, targetIndex + 1);
      return true;
    }
    function handleRecommendationPointerDown(event) {
      if (event.button !== undefined && event.button !== 0) return;
      if (event.target.closest('button, a, input, select, textarea, summary, .tooltip-trigger')) return;
      const card = event.target.closest('.sort-card[data-index]');
      if (!card) return;
      const index = Number(card.dataset.index);
      if (!Number.isInteger(index) || !currentRecommendations[index]) return;
      if (currentRecommendations[index].locked) return;
      pointerDragState = {
        index,
        startX: event.clientX,
        startY: event.clientY,
        active: false,
      };
    }
    function handleRecommendationPointerMove(event) {
      if (!pointerDragState || !currentRecommendations[pointerDragState.index]) return;
      const distance = Math.abs(event.clientX - pointerDragState.startX) + Math.abs(event.clientY - pointerDragState.startY);
      if (!pointerDragState.active && distance < 10) return;
      pointerDragState.active = true;
      draggedRecommendationIndex = pointerDragState.index;
      const card = document.querySelector(`.sort-card[data-index="${pointerDragState.index}"]`);
      if (card) card.classList.add('dragging');
      const target = sortDropTargetFromPoint(event.clientX, event.clientY);
      document.querySelectorAll('.sort-lane.drop-active').forEach(lane => lane.classList.remove('drop-active'));
      if (target && currentRecommendations[pointerDragState.index] && target.lane.dataset.riskGroup === cartRiskGroup(currentRecommendations[pointerDragState.index])) {
        target.lane.classList.add('drop-active');
      }
      event.preventDefault();
    }
    function handleRecommendationPointerUp(event) {
      if (!pointerDragState) return;
      const state = pointerDragState;
      pointerDragState = null;
      if (state.active) {
        const target = sortDropTargetFromPoint(event.clientX, event.clientY);
        if (target) applySortDrop(state.index, target.lane, target.targetCard);
        event.preventDefault();
      }
      draggedRecommendationIndex = null;
      clearSortDropState();
    }
    function toggleRecommendationLock(index) {
      if (!currentRecommendations[index]) return;
      currentRecommendations[index] = {
        ...currentRecommendations[index],
        locked: !currentRecommendations[index].locked,
      };
      markPlanOrderDirty();
      renderSortRows();
    }
    function refreshCurrentPlanViews() {
      renderSortRows();
      renderMatchedUniversityRows();
      renderInterestPreview();
      renderSelectionCart();
    }
    function handlePaginationClick(event) {
      const button = event.target.closest('button[data-page-target]');
      if (!button || button.disabled) return;
      const target = button.dataset.pageTarget;
      let value = button.dataset.pageValue;
      if (value === 'jump') {
        const pagination = button.closest('.pagination');
        const input = pagination && Array.from(pagination.querySelectorAll('input[data-page-jump-target]'))
          .find(item => item.dataset.pageJumpTarget === target);
        value = input ? input.value : '';
      }
      if (target === 'matched') {
        matchedPage = resolvePageAction(value, matchedPage, filteredCandidateRecommendations().length);
        renderMatchedUniversityRows();
      }
      if (target === 'recommendation') {
        recommendationPage = resolvePageAction(value, recommendationPage, currentRecommendations.length);
        renderSortRows();
      }
    }
    function handlePaginationJumpKeydown(event) {
      const input = event.target.closest('input[data-page-jump-target]');
      if (!input || event.key !== 'Enter') return;
      event.preventDefault();
      const target = input.dataset.pageJumpTarget;
      const pagination = input.closest('.pagination');
      const button = pagination && Array.from(pagination.querySelectorAll('button[data-page-target]'))
        .find(item => item.dataset.pageTarget === target && item.dataset.pageValue === 'jump');
      if (button && !button.disabled) button.click();
    }
    function handlePaginationSizeChange(event) {
      const select = event.target.closest('select[data-page-size-target]');
      if (!select) return;
      const nextSize = Number(select.value);
      if (!PAGE_SIZE_OPTIONS.includes(nextSize)) return;
      pageSize = nextSize;
      matchedPage = 1;
      recommendationPage = 1;
      if (select.dataset.pageSizeTarget === 'matched') {
        renderMatchedUniversityRows();
      } else if (select.dataset.pageSizeTarget === 'recommendation') {
        renderSortRows();
      }
    }
    function reportCacheSignature() {
      if (!latestPlanData) return '';
      return [
        latestPlanData.candidate && latestPlanData.candidate.rank,
        latestPlanData.plan && latestPlanData.plan.strategy,
        selectedOptionOrder.join('|'),
        selectedOptionKeys.size,
      ].join('::');
    }
    function buildReportHtml() {
      const signature = reportCacheSignature();
      if (signature && reportHtmlCache.signature === signature && reportHtmlCache.html) {
        return reportHtmlCache.html;
      }
      const html = buildReportHtmlUncached();
      reportHtmlCache = { signature, html };
      return html;
    }
    function buildReportHtmlUncached() {
      if (!latestPlanData) return '';
      const reportItems = selectedCartItems();
      const rows = reportItems.map((item, index) => {
        const meta = schoolMeta(item);
        const risks = charterReportText(item);
        const quality = evidenceQuality(item);
        const assessment = disciplineAssessmentInfo(item);
        return `<tr><td>${index + 1}</td><td>${escapeHtml(item.option_name)}<br><span class="muted">${escapeHtml(optionIdentity(item))}</span></td><td>${escapeHtml(meta.city)}</td><td>${escapeHtml(meta.tags.join('、'))}</td><td>${escapeHtml(assessment.assessment)}<br><span class="muted">保研率 ${escapeHtml(assessment.rate)}</span></td><td>${escapeHtml(item.risk_band)}</td><td>${fmt(item.weighted_reference_rank)}</td><td>${escapeHtml(quality.label)}</td><td>${escapeHtml(planChangeText(item))}</td><td>${escapeHtml(risks)}</td><td>${escapeHtml(majorKnowledgeText(item))}</td><td>${escapeHtml(recommendationExplanation(item))}</td></tr>`;
      }).join('');
      const edgeRows = (latestPlanData.edge_case_warnings || []).map(item => `<li>${item}</li>`).join('');
      const groups = cartCounts(reportItems);
      return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>志愿参考报告</title>
        <style>
          body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:#20251f;margin:30px;line-height:1.55;}
          h1{font-family:Songti SC,serif;margin:0 0 8px;font-size:28px;} h2{margin:22px 0 8px;font-size:18px;} h3{margin:14px 0 6px;font-size:14px;}
          .cover{border:2px solid #1f6f4c;padding:22px 24px;margin-bottom:18px;background:#fbf8f0;}
          .muted{color:#777368;font-size:12px;margin-bottom:12px;} .stamp{display:inline-block;border:1px solid #c9bda8;border-radius:999px;padding:3px 9px;margin-right:6px;font-size:12px;color:#625744;}
          .summary{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0;} .summary div{border:1px solid #ded6c7;background:#fffdf7;padding:9px;border-radius:6px;font-size:12px;} .summary b{display:block;color:#1f6f4c;font-size:18px;}
          table{width:100%;border-collapse:collapse;font-size:11px;page-break-inside:auto;} th,td{border:1px solid #ded6c7;padding:6px;vertical-align:top;} th{background:#faf5ea;text-align:left;} tr{page-break-inside:avoid;}
          .notice{border:1px solid #e5cfa4;background:#fff8eb;color:#68410d;padding:10px;border-radius:6px;font-size:12px;}
          .reference-warning{color:#c74747;font-weight:800;}
        </style></head><body>
        <section class="cover">
          <h1>山东高考志愿参考报告</h1>
          <div class="muted">生成时间 ${new Date().toLocaleString()} · 报告版本 ${APP_VERSION}</div>
          <span class="stamp">2026 位次 ${fmt(latestPlanData.candidate.rank)}</span>
          <span class="stamp">选科 ${latestPlanData.candidate.subjects.join('、')}</span>
          <span class="stamp">专业选择 ${latestPlanData.candidate.interests.length ? latestPlanData.candidate.interests.join('、') : '不限（全部）'}</span>
          <span class="stamp">当前方案 ${strategyLabels[latestPlanData.plan.strategy] || latestPlanData.plan.strategy}</span>
        </section>
        <div class="summary">
          <div><b>${fmt(reportItems.length)}</b>志愿数量</div>
          <div><b>${fmt(groups.challenge)}</b>冲类志愿</div>
          <div><b>${fmt(groups.steady)}</b>稳类志愿</div>
          <div><b>${fmt(groups.safe)}</b>保类志愿</div>
        </div>
        <div class="notice"><p class="reference-warning">重要提示：本报告和系统输出结果仅供参考，用户必须自行逐项核对官方数据。</p><p>2026 分专业招生计划与招生章程必须以山东省教育招生考试院和院校官方发布为准；当前系统会标出历史计划估算和章程规则风险，不能替代人工最终复核。</p></div>
        <h2>等效分换算</h2>
        <table><thead><tr><th>年份</th><th>位次</th><th>等效分</th><th>累计人数</th><th>来源</th></tr></thead><tbody>
        ${latestPlanData.equivalent_scores.map(item => `<tr><td>${item.year}</td><td>${fmt(item.rank)}</td><td>${item.score}</td><td>${fmt(item.cumulative_count)}</td><td>${item.source_id}</td></tr>`).join('')}
        </tbody></table>
        <h2>边界与责任提示</h2>
        <div class="notice"><ul>${edgeRows || '<li>当前输入未触发额外边界提示。</li>'}</ul></div>
        <h2>志愿清单</h2>
        <table><thead><tr><th>序号</th><th>专业 + 院校</th><th>所在地</th><th>标签</th><th>学科评估/保研率</th><th>档次</th><th>参考位次</th><th>证据等级</th><th>2026计划核查</th><th>章程风险</th><th>专业知识</th><th>依据</th></tr></thead><tbody>${rows}</tbody></table>
        <p class="reference-warning">提示：本报告仅供参考，正式填报前用户必须自行核对山东省教育招生考试院、招生院校 2026 年招生计划与招生章程。</p>
        </body></html>`;
    }
    function ensureReportReady() {
      if (!latestPlanData) {
        alert('请先生成志愿方案。');
        return false;
      }
      if (!selectedCartItems().length) {
        alert('请先在选择学校专业中加入清单。');
        return false;
      }
      return true;
    }
    function closeReportPreview() {
      const dialog = document.getElementById('reportPreviewDialog');
      const frame = document.getElementById('reportPreviewFrame');
      if (frame) frame.removeAttribute('srcdoc');
      if (dialog) dialog.classList.remove('open');
    }
    function previewReport() {
      if (!ensureReportReady()) return;
      const dialog = document.getElementById('reportPreviewDialog');
      const frame = document.getElementById('reportPreviewFrame');
      if (!dialog || !frame) return;
      frame.srcdoc = buildReportHtml();
      dialog.classList.add('open');
    }
    function openReportWindow({ print = false } = {}) {
      if (!ensureReportReady()) return null;
      const reportHtml = buildReportHtml();
      const reportUrl = URL.createObjectURL(new Blob([reportHtml], { type: 'text/html;charset=utf-8' }));
      const reportWindow = window.open(reportUrl, '_blank');
      if (!reportWindow) {
        URL.revokeObjectURL(reportUrl);
        alert('浏览器阻止了报告窗口，请允许弹出窗口后重试。');
        return null;
      }
      reportWindow.focus();
      if (print) {
        let printed = false;
        const printWhenReady = () => {
          if (printed) return;
          printed = true;
          try {
            reportWindow.focus();
            reportWindow.print();
          } finally {
            setTimeout(() => URL.revokeObjectURL(reportUrl), 5000);
          }
        };
        reportWindow.addEventListener('load', printWhenReady, { once: true });
        setTimeout(printWhenReady, 250);
      } else {
        setTimeout(() => URL.revokeObjectURL(reportUrl), 60000);
      }
      return reportWindow;
    }
    function exportPdfReport() {
      openReportWindow({ print: true });
    }
    function dataSourceManagerHtml() {
      return `<div class="data-source-manager">
        <div class="data-year-toolbar">
          <label><span>数据年度</span><select id="dataSourceYearSelect" aria-label="数据年度"></select></label>
          <div class="data-year-summary" id="dataSourceYearSummary">正在读取年度数据完整性...</div>
          <div class="year-add-wrap">
            <button type="button" class="secondary-button year-add-button" id="dataSourceAddYear">+ 新增年度</button>
            <div class="year-add-popover" id="dataSourceYearPopover">
              <h3>新增数据年度</h3>
              <label>年度 <input type="number" id="dataSourceNewYear" min="2020" max="2035" step="1" placeholder="2027"></label>
              <label class="checkline"><input type="checkbox" id="dataSourceCopyPrevious" checked>复制上一年度数据项配置</label>
              <label>基准年度 <select id="dataSourceBaseYear"></select></label>
              <div class="year-add-actions">
                <button type="button" class="secondary-button" id="dataSourceCancelYear">取消</button>
                <button type="button" id="dataSourceCreateYear">创建年度</button>
              </div>
            </div>
          </div>
          <details class="data-source-help">
            <summary>说明</summary>
            <div class="notice">数据源管理用于把零散收集的数据统一纳入系统：先导入，再在工作台中查看原始记录、搜索、分页、逐条修改并保存。保存会直接写入运行数据库或基础 CSV/JSON 文件，基础文件修改前会自动备份。</div>
          </details>
        </div>
        <div class="data-source-tabs" role="tablist" aria-label="数据源管理视图">
          <button type="button" class="data-source-tab is-active" role="tab" aria-selected="true" aria-controls="dataSourcePanelSources" data-source-tab="sources">年度清单</button>
          <button type="button" class="data-source-tab" role="tab" aria-selected="false" aria-controls="dataSourcePanelImport" data-source-tab="import">导入模板</button>
          <button type="button" class="data-source-tab" role="tab" aria-selected="false" aria-controls="dataSourcePanelRecords" data-source-tab="records">原始记录</button>
        </div>
        <div class="data-source-layout">
          <section class="data-source-panel data-source-tab-panel is-active" id="dataSourcePanelSources" role="tabpanel" data-source-panel="sources">
            <div class="data-panel-title">年度必备数据 <span id="dataSourcePanelHint">固定清单</span></div>
            <div class="data-source-status" id="dataSourceStatus">正在读取数据源清单...</div>
            <div class="data-source-table-wrap">
              <table class="data-source-table">
                <thead><tr><th>数据源</th><th>类型</th><th>状态</th><th>操作</th></tr></thead>
                <tbody id="dataSourceRows"><tr><td colspan="4">正在加载...</td></tr></tbody>
              </table>
            </div>
          </section>
          <section class="data-source-import-panel data-source-tab-panel" id="dataSourcePanelImport" role="tabpanel" data-source-panel="import">
            <div class="data-panel-title">导入与模板 <span id="dataSourceImportHint">当前数据项</span></div>
            <div class="data-source-status" id="dataSourceImportStatus">请选择左侧数据项导入或替换。</div>
            <div class="data-source-actions">
              <select id="dataSourceType" aria-label="数据类型">
                <option value="admission">历史招录/计划</option>
                <option value="score_rank">一分一段</option>
                <option value="major_catalog">专业目录</option>
                <option value="interest_map">专业标签</option>
                <option value="plan_supplement">招生计划补充</option>
                <option value="discipline_quality">学科评估/保研率</option>
                <option value="postgraduate_rates">保研率</option>
                <option value="school_info">高校信息/章程</option>
                <option value="official_status">官方状态核验</option>
              </select>
              <input type="number" id="dataSourceYear" min="2020" max="2035" step="1" placeholder="年度：如 2026">
              <select id="dataSourceMode" aria-label="导入模式">
                <option value="replace">替换同年度/同类型</option>
                <option value="append">追加导入</option>
              </select>
              <input type="file" id="dataSourceFile" accept=".csv,.xlsx,.xls,.json,.pdf,.docx,.html,.htm">
              <button type="button" id="dataSourceUpload">导入</button>
            </div>
            <div class="template-links" id="dataSourceTemplates"></div>
            <ul class="data-validation-list">
              <li>字段校验</li>
              <li>年度一致性</li>
              <li>重复记录检查</li>
              <li>自动备份策略</li>
            </ul>
          </section>
          <section class="data-record-panel data-source-tab-panel" id="dataSourcePanelRecords" role="tabpanel" data-source-panel="records">
            <div class="data-panel-title">原始记录预览与编辑 <span id="dataRecordStatus">请选择左侧数据源查看原始记录。</span></div>
            <div class="data-record-toolbar">
              <input type="search" id="dataRecordSearch" placeholder="搜索当前数据集的学校、专业、来源、备注等">
              <button type="button" class="secondary-button" id="dataRecordSearchButton">搜索</button>
              <button type="button" class="secondary-button" id="dataRecordRefreshButton">刷新</button>
            </div>
            <div class="data-record-list-wrap">
              <div class="data-record-list-head" id="dataRecordHead">原始记录</div>
              <div class="data-record-list" id="dataRecordRows"><div class="data-record-card">暂无数据。</div></div>
            </div>
            <div class="data-record-pager">
              <span id="dataRecordPagerInfo">第 0 / 0 页</span>
              <span class="pager-actions">
                <button type="button" class="secondary-button" id="dataRecordPrev">上一页</button>
                <button type="button" class="secondary-button" id="dataRecordNext">下一页</button>
              </span>
            </div>
          </section>
        </div>
      </div>`;
    }
    function formatBytes(value) {
      const size = Number(value || 0);
      if (!size) return '0 B';
      if (size < 1024) return `${fmt(size)} B`;
      if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
      return `${(size / 1024 / 1024).toFixed(1)} MB`;
    }
    function dataSourceTemplateLinks(payload) {
      const templates = payload && payload.templates || [];
      return templates.map(item =>
        `<a href="/api/data-sources/template?type=${encodeURIComponent(item.key)}" download="${escapeHtml(item.filename || '')}">${escapeHtml(item.label || item.key)}</a>`
      ).join('');
    }
    function dataSourceYears(payload) {
      const years = payload && payload.years || [];
      return years.map(String).filter(Boolean);
    }
    function activeDataSourceYear() {
      const selector = document.getElementById('dataSourceYearSelect');
      return String(selector?.value || dataSourceSelectedYear || dataSourceState?.current_year || '');
    }
    function activeDataSourceItems(payload) {
      const year = activeDataSourceYear();
      const yearlyItems = payload && payload.yearly_items || [];
      if (yearlyItems.length && year) {
        return yearlyItems.filter(item => String(item.year || '') === String(year));
      }
      return payload && payload.items || [];
    }
    function syncDataSourceYearInput() {
      const yearInput = document.getElementById('dataSourceYear');
      const year = activeDataSourceYear();
      if (yearInput && year) yearInput.value = year;
    }
    function syncDataSourceImportPanel(dataType = '', year = '', name = '') {
      const typeInput = document.getElementById('dataSourceType');
      const yearInput = document.getElementById('dataSourceYear');
      const hint = document.getElementById('dataSourceImportHint');
      const status = document.getElementById('dataSourceImportStatus');
      if (typeInput && dataType) typeInput.value = dataType;
      if (yearInput) yearInput.value = year || activeDataSourceYear() || '';
      if (hint) hint.textContent = name || dataType || '当前数据项';
      if (status && name) status.textContent = `当前：${name}。可下载模板后导入，或用新文件替换该数据项。`;
    }
    function setDataSourceTab(tab = 'sources') {
      const allowed = new Set(['sources', 'import', 'records']);
      dataSourceActiveTab = allowed.has(tab) ? tab : 'sources';
      document.querySelectorAll('[data-source-tab]').forEach(button => {
        const active = button.dataset.sourceTab === dataSourceActiveTab;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      document.querySelectorAll('[data-source-panel]').forEach(panel => {
        panel.classList.toggle('is-active', panel.dataset.sourcePanel === dataSourceActiveTab);
      });
    }
    function nextDataSourceYear(payload) {
      const years = dataSourceYears(payload).map(year => Number(year)).filter(Number.isFinite);
      const maxYear = years.length ? Math.max(...years) : Number(new Date().getFullYear());
      return String(maxYear + 1);
    }
    function renderDataSourceYearControls(payload) {
      const selector = document.getElementById('dataSourceYearSelect');
      const summary = document.getElementById('dataSourceYearSummary');
      const baseYear = document.getElementById('dataSourceBaseYear');
      const newYear = document.getElementById('dataSourceNewYear');
      const years = dataSourceYears(payload);
      if (!dataSourceSelectedYear) dataSourceSelectedYear = String(payload?.current_year || years[years.length - 1] || '');
      if (selector) {
        const current = dataSourceSelectedYear;
        selector.innerHTML = years.map(year => `<option value="${escapeHtml(year)}">${escapeHtml(year)} 年</option>`).join('');
        if (years.includes(current)) selector.value = current;
      }
      if (baseYear) {
        const selectedBase = baseYear.value;
        baseYear.innerHTML = years.map(year => `<option value="${escapeHtml(year)}">${escapeHtml(year)} 年</option>`).join('');
        baseYear.value = years.includes(selectedBase) ? selectedBase : String(activeDataSourceYear() || years[years.length - 1] || '');
      }
      if (newYear && !newYear.value) newYear.value = nextDataSourceYear(payload);
      const items = activeDataSourceItems(payload);
      const required = items.length;
      const ready = items.filter(item => item.status !== '待导入' && item.status !== '缺失').length;
      const editable = items.filter(item => item.record_viewable).length;
      const missing = items.filter(item => item.status === '待导入' || item.status === '缺失').map(item => item.category_label || item.name).slice(0, 4);
      if (summary) {
        const progress = required ? Math.round((ready / required) * 100) : 0;
        summary.innerHTML = `<div><b>${escapeHtml(activeDataSourceYear())}</b> 数据完整性 ${fmt(ready)}/${fmt(required)} · ${fmt(editable)} 项可查看/编辑</div><div class="data-year-progress"><span style="width:${progress}%"></span></div>${missing.length ? `<div class="data-year-missing">待补：${escapeHtml(missing.join('、'))}</div>` : ''}`;
      }
      syncDataSourceYearInput();
    }
    function dataSourceRowHtml(item) {
      const uploaded = item.source_type === 'user_uploaded';
      const database = item.source_type === 'database';
      const managed = item.source_type === 'managed_file';
      const active = dataRecordSelection
        && dataRecordSelection.dataType === item.category
        && String(dataRecordSelection.year || '') === String(item.year || '');
      const chip = `<span class="source-chip ${uploaded ? 'uploaded' : ''}">${escapeHtml(item.source_type_label || '')}</span>`;
      const digest = item.sha256 ? `${String(item.sha256).slice(0, 12)}...` : '无校验值';
      const note = item.description ? `<div class="mini">${escapeHtml(item.description)}</div>` : '';
      const year = item.year ? `<div class="mini">年度 ${escapeHtml(item.year)}</div>` : '';
      const recordCount = item.record_count !== '' && item.record_count !== undefined ? `<div class="mini">${fmt(item.record_count)} 条记录</div>` : '';
      const capabilities = [
        item.importable ? '可导入' : '',
        item.record_viewable ? '可查看/编辑' : '',
        item.exportable ? '可导出' : '',
        item.deletable ? '可删除' : '',
      ].filter(Boolean).join(' / ');
      const exportUrl = item.exportable
        ? `/api/data-sources/export?type=${encodeURIComponent(item.category || '')}${item.year ? `&year=${encodeURIComponent(item.year)}` : ''}`
        : '';
      const exportAction = exportUrl ? `<a class="secondary-button inline-button" href="${exportUrl}" download>导出</a>` : '';
      const recordAction = item.record_viewable
        ? `<button type="button" class="secondary-button" data-source-records="${escapeHtml(item.id)}" data-source-type="${escapeHtml(item.category || '')}" data-source-year="${escapeHtml(item.year || '')}" data-source-name="${escapeHtml(item.name || '')}">查看/编辑</button>`
        : '';
      const replaceText = item.status === '待导入' || item.status === '缺失' ? '导入' : '替换';
      const replaceAction = item.importable
        ? `<button type="button" class="secondary-button" data-source-replace="${escapeHtml(item.id)}" data-source-type="${escapeHtml(item.category || '')}" data-source-year="${escapeHtml(item.year || '')}" data-source-name="${escapeHtml(item.name || '')}">${replaceText}</button>`
        : '';
      const deleteAction = item.deletable
        ? `<button type="button" class="secondary-button danger-text-button" data-source-delete="${escapeHtml(item.id)}" data-source-type="${escapeHtml(item.category || '')}" data-source-year="${escapeHtml(item.year || '')}">删除</button>`
        : item.status === '待导入' || item.status === '缺失' ? '' : '<span class="mini">保护</span>';
      const action = `<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">${recordAction}${replaceAction}${exportAction}${deleteAction}</div>`;
      return `<tr class="${active ? 'is-active' : ''}">
        <td><div class="source-name">${escapeHtml(item.name || item.path || item.id)}</div>${note}${year}${recordCount}</td>
        <td>${chip}<div class="mini">${escapeHtml(item.category_label || '')}</div>${capabilities ? `<div class="mini">${escapeHtml(capabilities)}</div>` : ''}</td>
        <td>${escapeHtml(item.status || '')}<div class="mini">${escapeHtml(item.summary || '')}</div><div class="mini">${escapeHtml(item.uploaded_at || item.updated_at || '')}</div></td>
        <td>${action}<div class="mini">${formatBytes(item.size)} · SHA256 ${escapeHtml(digest)}</div></td>
      </tr>`;
    }
    function currentRecordQuery() {
      return String(document.getElementById('dataRecordSearch')?.value || '').trim();
    }
    function recordCellValue(row, column) {
      const values = row && row.values || {};
      return values[column.key] === null || values[column.key] === undefined ? '' : String(values[column.key]);
    }
    function dataRecordHeaderHtml(columns) {
      return `<span>字段 ${fmt(columns.length)} 个</span><span>每条记录以卡片展示，可逐字段修改后保存</span>`;
    }
    function dataRecordFieldUsesTextarea(column, value) {
      const key = String(column.key || '').toLowerCase();
      return String(value || '').length > 48 || /note|remark|url|tag|subject|description|summary|source/.test(key);
    }
    function dataRecordRowHtml(row, columns) {
      const cells = columns.map(column => {
        const readonly = column.editable === false;
        const value = recordCellValue(row, column);
        const label = escapeHtml(column.label || column.key);
        const key = escapeHtml(column.key);
        const title = escapeHtml(value);
        const control = dataRecordFieldUsesTextarea(column, value)
          ? `<textarea class="data-record-textarea" ${readonly ? 'readonly' : ''} data-record-field="${key}" title="${title}">${escapeHtml(value)}</textarea>`
          : `<input class="data-record-input" ${readonly ? 'readonly' : ''} data-record-field="${key}" value="${title}" title="${title}">`;
        return `<label class="data-record-field"><span>${label}</span>${control}</label>`;
      }).join('');
      return `<article class="data-record-card" data-record-key="${escapeHtml(row.key)}">
        <div class="data-record-card-head"><b>原始记录 ${escapeHtml(row.key)}</b><button type="button" class="secondary-button" data-record-save="${escapeHtml(row.key)}">保存</button></div>
        <div class="data-record-field-grid">${cells}</div>
      </article>`;
    }
    function renderDataRecords(payload) {
      dataRecordPayload = payload;
      const head = document.getElementById('dataRecordHead');
      const rows = document.getElementById('dataRecordRows');
      const status = document.getElementById('dataRecordStatus');
      const pager = document.getElementById('dataRecordPagerInfo');
      const prev = document.getElementById('dataRecordPrev');
      const next = document.getElementById('dataRecordNext');
      const columns = payload && payload.columns || [];
      const records = payload && payload.rows || [];
      const total = Number(payload && payload.total || 0);
      const page = Number(payload && payload.page || 1);
      const pageSize = Number(payload && payload.page_size || 25);
      const totalPages = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
      dataRecordPage = page;
      if (head) head.innerHTML = columns.length ? dataRecordHeaderHtml(columns) : '原始记录';
      if (rows) {
        rows.innerHTML = records.length
          ? records.map(row => dataRecordRowHtml(row, columns)).join('')
          : '<div class="data-record-card">当前条件下没有记录。</div>';
      }
      if (status) {
        const selectedName = dataRecordSelection ? dataRecordSelection.name : '未选择数据源';
        status.textContent = `${selectedName}：共 ${fmt(total)} 条原始记录，可编辑字段 ${fmt(columns.filter(item => item.editable !== false).length)} 个。`;
      }
      if (pager) pager.textContent = `第 ${fmt(page)} / ${fmt(totalPages)} 页 · 每页 ${fmt(pageSize)} 条`;
      if (prev) prev.disabled = page <= 1;
      if (next) next.disabled = page >= totalPages;
    }
    async function loadDataSourceRecords({ keepPage = false } = {}) {
      const status = document.getElementById('dataRecordStatus');
      if (!dataRecordSelection) {
        if (status) status.textContent = '请选择左侧数据源查看原始记录。';
        return;
      }
      if (!keepPage) dataRecordPage = 1;
      if (status) status.textContent = '正在读取原始记录...';
      const params = new URLSearchParams({
        type: dataRecordSelection.dataType || '',
        page: String(dataRecordPage),
        page_size: '25',
      });
      if (dataRecordSelection.year) params.set('year', dataRecordSelection.year);
      const query = currentRecordQuery();
      if (query) params.set('q', query);
      try {
        const response = await fetch(`/api/data-sources/records?${params.toString()}`);
        if (!response.ok) throw new Error(await response.text());
        renderDataRecords(await response.json());
        renderDataSources(dataSourceState);
      } catch (error) {
        if (status) status.textContent = `原始记录读取失败：${error.message || error}`;
      }
    }
    function openDataSourceRecords(dataType = '', year = '', name = '', options = {}) {
      if (!dataType) return;
      dataRecordSelection = { dataType, year: year || '', name: name || dataType };
      dataRecordPage = 1;
      syncDataSourceImportPanel(dataType, year, name);
      if (options.switchTab !== false) setDataSourceTab('records');
      loadDataSourceRecords();
    }
    function collectRecordValues(row) {
      const values = {};
      row.querySelectorAll('input[data-record-field]:not([readonly]), textarea[data-record-field]:not([readonly])').forEach(input => {
        values[input.dataset.recordField] = input.value;
      });
      return values;
    }
    async function saveDataRecord(key) {
      if (!dataRecordSelection || !key) return;
      const row = document.querySelector(`tr[data-record-key="${CSS.escape(key)}"]`);
      if (!row) return;
      const status = document.getElementById('dataRecordStatus');
      if (status) status.textContent = '正在保存记录...';
      try {
        const response = await fetch('/api/data-sources/records/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            data_type: dataRecordSelection.dataType,
            year: dataRecordSelection.year,
            key,
            values: collectRecordValues(row),
          }),
        });
        if (!response.ok) throw new Error(await response.text());
        await loadDataSourceRecords({ keepPage: true });
        await loadDataSources();
      } catch (error) {
        if (status) status.textContent = `记录保存失败：${error.message || error}`;
      }
    }
    function renderDataSources(payload) {
      dataSourceState = payload;
      const rows = document.getElementById('dataSourceRows');
      const status = document.getElementById('dataSourceStatus');
      const templates = document.getElementById('dataSourceTemplates');
      if (templates) templates.innerHTML = dataSourceTemplateLinks(payload);
      renderDataSourceYearControls(payload);
      const items = activeDataSourceItems(payload);
      if (rows) {
        rows.innerHTML = items.length
          ? items.map(dataSourceRowHtml).join('')
          : '<tr><td colspan="4">暂无数据源记录。</td></tr>';
      }
      if (status) {
        status.textContent = `${activeDataSourceYear()} 年数据清单 ${fmt(items.length)} 项；全部台账 ${fmt((payload?.items || []).length)} 条，上传留痕 ${fmt(payload?.upload_count || 0)} 条。`;
      }
      if (dataRecordSelection && String(dataRecordSelection.year || activeDataSourceYear()) !== String(activeDataSourceYear()) && dataRecordSelection.year) {
        dataRecordSelection = null;
        dataRecordPayload = null;
        renderDataRecords({ columns: [], rows: [], total: 0, page: 1, page_size: 25 });
      }
      if (!dataRecordSelection) {
        const first = items.find(item => item.record_viewable);
        if (first) openDataSourceRecords(first.category || '', first.year || '', first.name || '', { switchTab: false });
      }
    }
    async function loadDataSources() {
      const status = document.getElementById('dataSourceStatus');
      if (status) status.textContent = '正在读取数据源清单...';
      try {
        const response = await fetch('/api/data-sources');
        if (!response.ok) throw new Error(await response.text());
        renderDataSources(await response.json());
      } catch (error) {
        if (status) status.textContent = `读取失败：${error.message || error}`;
      }
    }
    async function uploadDataSource() {
      const fileInput = document.getElementById('dataSourceFile');
      const status = document.getElementById('dataSourceImportStatus') || document.getElementById('dataSourceStatus');
      const file = fileInput && fileInput.files && fileInput.files[0];
      if (!file) {
        alert(dataSourceEditTarget ? '请选择用于替换当前数据源的新文件。' : '请选择要导入的数据文件。');
        return;
      }
      const formData = new FormData();
      formData.append('file', file);
      formData.append('data_type', document.getElementById('dataSourceType')?.value || 'admission');
      formData.append('category', document.getElementById('dataSourceType')?.value || 'admission');
      formData.append('year', document.getElementById('dataSourceYear')?.value || '');
      formData.append('mode', document.getElementById('dataSourceMode')?.value || 'replace');
      if (dataSourceEditTarget) formData.append('edit_target', dataSourceEditTarget.id || '');
      if (status) status.textContent = dataSourceEditTarget ? '正在替换导入...' : '正在导入...';
      try {
        const response = await fetch('/api/data-sources/import', { method: 'POST', body: formData });
        if (!response.ok) throw new Error(await response.text());
        if (fileInput) fileInput.value = '';
        dataSourceEditTarget = null;
        const uploadButton = document.getElementById('dataSourceUpload');
        if (uploadButton) uploadButton.textContent = '导入';
        await loadDataSources();
        setDataSourceTab('sources');
        if (dataRecordSelection) await loadDataSourceRecords({ keepPage: true });
      } catch (error) {
        if (status) status.textContent = `${dataSourceEditTarget ? '替换导入' : '导入'}失败：${error.message || error}`;
      }
    }
    function replaceDataSource(sourceId, dataType = '', year = '', name = '') {
      const typeInput = document.getElementById('dataSourceType');
      const yearInput = document.getElementById('dataSourceYear');
      const modeInput = document.getElementById('dataSourceMode');
      const fileInput = document.getElementById('dataSourceFile');
      const uploadButton = document.getElementById('dataSourceUpload');
      const status = document.getElementById('dataSourceImportStatus') || document.getElementById('dataSourceStatus');
      dataSourceEditTarget = { id: sourceId, dataType, year, name };
      setDataSourceTab('import');
      syncDataSourceImportPanel(dataType, year, name);
      if (typeInput && dataType) typeInput.value = dataType;
      if (yearInput) yearInput.value = year || '';
      if (modeInput) modeInput.value = 'replace';
      if (uploadButton) uploadButton.textContent = '替换导入';
      if (status) {
        status.textContent = `准备替换：${name || sourceId}。请选择新文件后点击“替换导入”，系统会替换对应${year ? ` ${year} 年度` : ''}数据。`;
      }
      if (fileInput) {
        fileInput.focus();
        fileInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
    async function deleteDataSource(sourceId, dataType = '', year = '') {
      if (!sourceId) return;
      const label = year ? `${dataType} ${year}` : dataType || sourceId;
      if (!confirm(`确定删除数据源 ${label} 吗？删除前系统会尽量备份基础文件；年度数据库数据会从运行库移除。`)) return;
      const status = document.getElementById('dataSourceStatus');
      if (status) status.textContent = '正在删除...';
      try {
        const response = await fetch('/api/data-sources/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: sourceId, data_type: dataType, year }),
        });
        if (!response.ok) throw new Error(await response.text());
        if (dataRecordSelection && dataRecordSelection.dataType === dataType && String(dataRecordSelection.year || '') === String(year || '')) {
          dataRecordSelection = null;
          renderDataRecords({ columns: [], rows: [], total: 0, page: 1, page_size: 25 });
        }
        await loadDataSources();
      } catch (error) {
        if (status) status.textContent = `删除失败：${error.message || error}`;
      }
    }
    function toggleDataSourceYearPopover(open = null) {
      const popover = document.getElementById('dataSourceYearPopover');
      if (!popover) return;
      const shouldOpen = open === null ? !popover.classList.contains('open') : open;
      if (shouldOpen) {
        const input = document.getElementById('dataSourceNewYear');
        if (input && !input.value) input.value = nextDataSourceYear(dataSourceState);
      }
      popover.classList.toggle('open', shouldOpen);
    }
    async function createDataSourceYear() {
      const input = document.getElementById('dataSourceNewYear');
      const copyPrevious = document.getElementById('dataSourceCopyPrevious');
      const baseYear = document.getElementById('dataSourceBaseYear');
      const status = document.getElementById('dataSourceStatus');
      const year = String(input?.value || '').trim();
      if (!/^\d{4}$/.test(year)) {
        alert('请输入 4 位年度，例如 2027。');
        return;
      }
      if (status) status.textContent = `正在创建 ${year} 年度...`;
      try {
        const response = await fetch('/api/data-sources/years/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            year,
            copy_previous: Boolean(copyPrevious && copyPrevious.checked),
            base_year: baseYear?.value || activeDataSourceYear(),
          }),
        });
        if (!response.ok) throw new Error(await response.text());
        const result = await response.json();
        dataSourceSelectedYear = String(result.year || year);
        dataRecordSelection = null;
        dataRecordPayload = null;
        renderDataRecords({ columns: [], rows: [], total: 0, page: 1, page_size: 25 });
        toggleDataSourceYearPopover(false);
        if (input) input.value = '';
        setDataSourceTab('sources');
        await loadDataSources();
      } catch (error) {
        if (status) status.textContent = `创建年度失败：${error.message || error}`;
      }
    }
    function initDataSourceManager() {
      if (dataSourceManagerInitialized) {
        loadDataSources();
        return;
      }
      dataSourceManagerInitialized = true;
      document.querySelectorAll('button[data-source-tab]').forEach(button => {
        button.addEventListener('click', () => setDataSourceTab(button.dataset.sourceTab || 'sources'));
      });
      setDataSourceTab(dataSourceActiveTab || 'sources');
      const uploadButton = document.getElementById('dataSourceUpload');
      if (uploadButton) uploadButton.addEventListener('click', uploadDataSource);
      const addYearButton = document.getElementById('dataSourceAddYear');
      if (addYearButton) addYearButton.addEventListener('click', () => toggleDataSourceYearPopover());
      const cancelYearButton = document.getElementById('dataSourceCancelYear');
      if (cancelYearButton) cancelYearButton.addEventListener('click', () => toggleDataSourceYearPopover(false));
      const createYearButton = document.getElementById('dataSourceCreateYear');
      if (createYearButton) createYearButton.addEventListener('click', createDataSourceYear);
      const yearSelector = document.getElementById('dataSourceYearSelect');
      if (yearSelector) {
        yearSelector.addEventListener('change', () => {
          dataSourceSelectedYear = String(yearSelector.value || '');
          dataRecordSelection = null;
          dataRecordPayload = null;
          renderDataRecords({ columns: [], rows: [], total: 0, page: 1, page_size: 25 });
          setDataSourceTab('sources');
          renderDataSources(dataSourceState);
        });
      }
      const rows = document.getElementById('dataSourceRows');
      if (rows) {
        rows.addEventListener('click', event => {
          const recordsButton = event.target.closest('button[data-source-records]');
          if (recordsButton) {
            openDataSourceRecords(
              recordsButton.dataset.sourceType || '',
              recordsButton.dataset.sourceYear || '',
              recordsButton.dataset.sourceName || '',
            );
            return;
          }
          const replaceButton = event.target.closest('button[data-source-replace]');
          if (replaceButton) {
            replaceDataSource(
              replaceButton.dataset.sourceReplace,
              replaceButton.dataset.sourceType || '',
              replaceButton.dataset.sourceYear || '',
              replaceButton.dataset.sourceName || '',
            );
            return;
          }
          const button = event.target.closest('button[data-source-delete]');
          if (button) deleteDataSource(button.dataset.sourceDelete, button.dataset.sourceType || '', button.dataset.sourceYear || '');
        });
      }
      const recordRows = document.getElementById('dataRecordRows');
      if (recordRows) {
        recordRows.addEventListener('click', event => {
          const saveButton = event.target.closest('button[data-record-save]');
          if (saveButton) saveDataRecord(saveButton.dataset.recordSave || '');
        });
      }
      const searchButton = document.getElementById('dataRecordSearchButton');
      if (searchButton) searchButton.addEventListener('click', () => loadDataSourceRecords());
      const refreshButton = document.getElementById('dataRecordRefreshButton');
      if (refreshButton) refreshButton.addEventListener('click', () => loadDataSourceRecords({ keepPage: true }));
      const searchInput = document.getElementById('dataRecordSearch');
      if (searchInput) {
        searchInput.addEventListener('keydown', event => {
          if (event.key === 'Enter') {
            event.preventDefault();
            loadDataSourceRecords();
          }
        });
      }
      const prev = document.getElementById('dataRecordPrev');
      if (prev) prev.addEventListener('click', () => {
        if (dataRecordPage > 1) {
          dataRecordPage -= 1;
          loadDataSourceRecords({ keepPage: true });
        }
      });
      const next = document.getElementById('dataRecordNext');
      if (next) next.addEventListener('click', () => {
        const total = Number(dataRecordPayload && dataRecordPayload.total || 0);
        const pageSize = Number(dataRecordPayload && dataRecordPayload.page_size || 25);
        const totalPages = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
        if (dataRecordPage < totalPages) {
          dataRecordPage += 1;
          loadDataSourceRecords({ keepPage: true });
        }
      });
      loadDataSources();
    }
    const infoContent = {
      source: {
        title: '数据源管理',
        sub: '导入、统一展示、搜索、编辑和模板下载',
        body: dataSourceManagerHtml(),
      },
      guide: {
        title: '使用说明书',
        sub: '推荐操作顺序',
        body: '<ol><li>先输入 2026 全省位次、选科和专业选择。</li><li>点击生成方案，系统会完成后台计算并匹配学校专业。</li><li>在选择学校专业里搜索你关心的学校或专业；多个关键词用空格隔开，比如“山东大学 计算机科学与技术”。</li><li>点击“加入”保留候选；再次点击“已加入”可移出，右侧已选清单会实时按冲、稳、保汇总。</li><li>重点查看每个候选里的证据、章程链接、身体条件和计划提醒。</li><li>最后一定要逐条打开招生章程和 2026 官方计划核对。</li></ol>',
      },
      compliance: {
        title: '使用前须知与免责声明',
        sub: '本地离线、隐私保护、仅供参考',
        body: '<p class="reference-warning"><b>仅供参考：</b>本软件生成的志愿方案和分析内容只供参考，用户必须自行核对官方招生计划、招生章程和填报系统信息。</p><p><b>本地离线：</b>软件只在用户电脑本机运行，浏览器访问的是 127.0.0.1 本机地址；没有云端后台、远程服务器、远程数据库或远程账号中心，断网后仍可使用已内置的数据功能。</p><p><b>我们看不到：</b>位次、选科、专业选择、筛选条件和生成结果都只留在用户本机。除非用户主动发送截图、报告或软件文件，否则开发方/销售方不知道用户填了什么、生成了什么方案。</p><p><b>使用方式：</b>当前版本不要求账号密码，也不要求本机授权或机器码绑定；解压启动后即可使用。</p>',
      },
      version: {
        title: '详细更新记录',
        sub: 'V1.0 版本',
        body: '<p><b>当前版本：V1.0 版本。</b></p><p><b>专业选择：</b>界面口径由宽泛方向词调整为标准化“专业选择”，优先对齐教育部《普通高等学校本科专业目录（2026年）》标准专业名称，并补充山东普通类常规批投档表中的招生专业名称。</p><p><b>筛选准确性：</b>标准专业名会同步识别所属专业类，例如计算机类、电子信息类、临床医学类等，减少因山东招生专业按专业类或方向发布造成的漏筛。</p><p><b>报告速度：</b>报告预览和导出增加本地缓存，未改动清单时重复点击直接复用已生成报告；导出打印改为页面加载完成即触发，并保留兜底等待。</p><p><b>数据与责任：</b>继续保留官方数据来源提示、须知与免责、报告预览与导出能力；2026 分专业招生计划未接入官方完整数据时继续显示估算或待接入，避免误导。</p>',
      },
    };
    function startupAgreementHtml(body) {
      return `<div class="agreement-box">
        ${body}
        <label class="agreement-checkline">
          <input type="checkbox" id="startupAgreementCheckbox">
          <span>我已阅读并同意以上使用约定，知悉本系统仅供参考，正式填报前必须自行核对官方招生计划、招生章程和填报系统信息。</span>
        </label>
        <div class="agreement-actions">
          <button type="button" class="secondary-button" id="startupAgreementCancel">取消</button>
          <button type="button" id="startupAgreementConfirm" disabled>同意并进入系统</button>
        </div>
      </div>`;
    }
    function openDataSourceWorkbench() {
      const workbench = document.getElementById('dataSourceWorkbench');
      const backdrop = document.getElementById('dataSourceWorkbenchBackdrop');
      const body = document.getElementById('dataSourceWorkbenchBody');
      if (!workbench || !backdrop || !body) return;
      if (!body.dataset.ready) {
        body.innerHTML = dataSourceManagerHtml();
        body.dataset.ready = '1';
        dataSourceManagerInitialized = false;
      }
      workbench.classList.add('open');
      workbench.setAttribute('aria-hidden', 'false');
      backdrop.classList.add('open');
      initDataSourceManager();
    }
    function closeDataSourceWorkbench() {
      const workbench = document.getElementById('dataSourceWorkbench');
      const backdrop = document.getElementById('dataSourceWorkbenchBackdrop');
      if (workbench) {
        workbench.classList.remove('open');
        workbench.setAttribute('aria-hidden', 'true');
      }
      if (backdrop) backdrop.classList.remove('open');
      const popover = document.getElementById('dataSourceYearPopover');
      if (popover) popover.classList.remove('open');
    }
    function openInfoDialog(kind, options = {}) {
      if (kind === 'source' && !options.requireAgreement) {
        openDataSourceWorkbench();
        return;
      }
      const item = infoContent[kind] || infoContent.source;
      activeInfoDialogKind = kind;
      startupAgreementRequired = Boolean(options.requireAgreement);
      const dialog = document.getElementById('infoDialog');
      const closeButton = document.getElementById('infoDialogClose');
      const panel = dialog && dialog.querySelector('.dialog');
      if (panel) panel.style.width = kind === 'source' ? 'min(980px, 100%)' : 'min(640px, 100%)';
      dialog.classList.toggle('startup-agreement-dialog', startupAgreementRequired);
      closeButton.hidden = startupAgreementRequired;
      document.getElementById('infoDialogTitle').textContent = item.title;
      document.getElementById('infoDialogSub').textContent = startupAgreementRequired ? '请阅读并勾选同意后进入系统' : item.sub;
      closeButton.textContent = '关闭';
      document.getElementById('infoDialogBody').innerHTML = startupAgreementRequired
        ? startupAgreementHtml(item.body)
        : item.body;
      dialog.classList.add('open');
      if (kind === 'source' && !startupAgreementRequired) initDataSourceManager();
    }
    function cancelStartupAgreement() {
      document.body.innerHTML = `<main class="cancel-page">
        <section class="cancel-panel">
          <h1>已取消使用</h1>
          <p>你没有同意使用前须知与免责声明，因此系统未进入使用界面。关闭此窗口或刷新页面后可重新选择。</p>
          <button type="button" id="cancelPageClose">关闭窗口</button>
        </section>
      </main>`;
      const closeButton = document.getElementById('cancelPageClose');
      if (closeButton) {
        closeButton.addEventListener('click', () => {
          window.close();
          closeButton.textContent = '请手动关闭此窗口';
        });
      }
    }
    function acceptStartupAgreement() {
      startupAgreementRequired = false;
      closeInfoDialog();
      (startupReadyPromise || Promise.resolve()).finally(() => {
        startApp();
      });
    }
    function closeInfoDialog() {
      if (startupAgreementRequired) {
        cancelStartupAgreement();
        return;
      }
      document.getElementById('infoDialog').classList.remove('open');
      document.getElementById('infoDialog').classList.remove('startup-agreement-dialog');
      document.getElementById('infoDialogClose').hidden = false;
      activeInfoDialogKind = '';
    }
    form.addEventListener('submit', event => {
      event.preventDefault();
      loadPlan().catch(error => alert(error.message));
    });
    form.addEventListener('input', event => {
      if (event.target.closest('#interestPickerDialog') || event.target.closest('#interestDialog') || event.target.closest('#subjectDialog')) return;
      if (event.target.name === 'targetSize') {
        scaleCustomGroupsToTarget();
        syncCustomPlanPanel();
        renderSelectionCart();
        renderStrategyComparison(latestPlanData);
      }
      if (event.target.name && event.target.name.startsWith('customQuota')) {
        syncCustomPlanPanel();
        renderSelectionCart();
      }
      if (event.target.name) syncProfileFilterSummary();
      if (event.target.name) markSettingsDirty();
    });
    form.addEventListener('change', event => {
      if (event.target.closest('#interestPickerDialog') || event.target.closest('#interestDialog') || event.target.closest('#subjectDialog')) return;
      if (event.target.name === 'strategy') {
        syncCustomPlanPanel();
        renderSelectionCart();
        renderStrategyComparison(latestPlanData);
      }
      if (event.target.name === 'targetSize') {
        scaleCustomGroupsToTarget();
        syncCustomPlanPanel();
        renderSelectionCart();
        renderStrategyComparison(latestPlanData);
      }
      if (event.target.name && event.target.name.startsWith('customQuota')) {
        syncCustomPlanPanel();
        renderSelectionCart();
      }
      if (event.target.name) syncProfileFilterSummary();
      if (event.target.name) markSettingsDirty();
    });
    function handleRecommendationActionClick(event) {
      const button = event.target.closest('button[data-action]');
      if (!button) return;
      const index = Number(button.dataset.index);
      const action = button.dataset.action;
      if (Number.isNaN(index) || !currentRecommendations[index]) return;
      if (action === 'up') {
        moveRecommendation(index, -1);
        return;
      }
      if (action === 'down') {
        moveRecommendation(index, 1);
        return;
      }
      if (action === 'lock') {
        toggleRecommendationLock(index);
        return;
      }
      if (action === 'move-to') {
        const control = button.closest('.move-to-control');
        const input = control && control.querySelector('input[data-move-target]');
        const target = Number(String(input && input.value || '').trim());
        if (!Number.isInteger(target) || target < 1 || target > currentRecommendations.length) {
          if (input) input.focus();
          alert(`请输入 1 到 ${currentRecommendations.length} 之间的整数。`);
          return;
        }
        moveRecommendationTo(index, target);
        return;
      }
      if (action === 'delete') {
        removeSelectedOption(currentRecommendations[index].option_key);
        currentRecommendations.splice(index, 1);
        markPlanOrderDirty();
      }
      refreshCurrentPlanViews();
    }
    function handleRecommendationActionKeydown(event) {
      const input = event.target.closest('input[data-move-target]');
      if (!input || event.key !== 'Enter') return;
      event.preventDefault();
      const control = input.closest('.move-to-control');
      const button = control && control.querySelector('button[data-action="move-to"]');
      if (button) button.click();
    }
    function addListener(id, type, handler) {
      const target = document.getElementById(id);
      if (target) target.addEventListener(type, handler);
    }
    addListener('recommendationRows', 'click', handleRecommendationActionClick);
    addListener('recommendationRows', 'keydown', handleRecommendationActionKeydown);
    addListener('recommendationRows', 'dragstart', handleRecommendationDragStart);
    addListener('recommendationRows', 'dragover', handleRecommendationDragOver);
    addListener('recommendationRows', 'drop', handleRecommendationDrop);
    addListener('recommendationRows', 'dragend', handleRecommendationDragEnd);
    addListener('recommendationRows', 'pointerdown', handleRecommendationPointerDown);
    document.addEventListener('pointermove', handleRecommendationPointerMove);
    document.addEventListener('pointerup', handleRecommendationPointerUp);
    addListener('cartDockButton', 'click', openSelectionDrawer);
    addListener('openSelectionDrawer', 'click', openSelectionDrawer);
    addListener('closeSelectionDrawer', 'click', closeSelectionDrawer);
    addListener('drawerCloseFooter', 'click', closeSelectionDrawer);
    addListener('pinSelectionCart', 'click', pinSelectionCartSidebar);
    addListener('unpinSelectionCart', 'click', unpinSelectionCartSidebar);
    addListener('selectionDrawerBackdrop', 'click', closeSelectionDrawer);
    addListener('dataSourceWorkbenchClose', 'click', closeDataSourceWorkbench);
    addListener('dataSourceWorkbenchBackdrop', 'click', closeDataSourceWorkbench);
    addListener('cartClearSelected', 'click', clearSelectedCart);
    addListener('drawerClearSelected', 'click', clearSelectedCart);
    addListener('selectionDrawerResize', 'pointerdown', startDrawerResize);
    addListener('openStrategySettings', 'click', () => openSettingsSlide('strategy'));
    addListener('openProfileSettings', 'click', () => openSettingsSlide('profile'));
    addListener('closeSettingsSlide', 'click', closeSettingsSlide);
    addListener('settingsSlideBackdrop', 'click', closeSettingsSlide);
    window.addEventListener('pointermove', handleDrawerResizeMove);
    window.addEventListener('pointerup', stopDrawerResize);
    window.addEventListener('resize', () => applyDrawerWidth());
    document.querySelector('.cart-count-grid').addEventListener('click', event => {
      const button = event.target.closest('button[data-cart-risk-filter]');
      if (!button) return;
      candidateRiskFilter = button.dataset.cartRiskFilter;
      matchedPage = 1;
      renderMatchedUniversityRows();
      setActiveStep('2');
    });
    document.getElementById('selectionDrawerGroups').addEventListener('click', event => {
      const moveButton = event.target.closest('button[data-cart-move]');
      if (moveButton && !moveButton.disabled) {
        moveSelectedOption(moveButton.dataset.cartMove, Number(moveButton.dataset.cartDelta));
        return;
      }
      const jumpButton = event.target.closest('button[data-cart-jump]');
      if (jumpButton) {
        const input = document.querySelector(`input[data-cart-position="${CSS.escape(jumpButton.dataset.cartJump)}"]`);
        const target = Number(String(input && input.value || '').trim());
        if (!Number.isInteger(target) || target < 1 || target > selectedOptionOrder.length) {
          if (input) input.focus();
          alert(`请输入 1 到 ${fmt(selectedOptionOrder.length)} 之间的整数。`);
          return;
        }
        moveSelectedOptionTo(jumpButton.dataset.cartJump, target);
        return;
      }
      const button = event.target.closest('button[data-cart-remove]');
      if (!button) return;
      removeSelectedOption(button.dataset.cartRemove);
      matchedPage = 1;
      syncRecommendationsFromSelection();
      renderMatchedUniversityRows();
      renderSelectionCart();
    });
    document.getElementById('selectionDrawerGroups').addEventListener('keydown', event => {
      const input = event.target.closest('input[data-cart-position]');
      if (!input || event.key !== 'Enter') return;
      event.preventDefault();
      const target = Number(String(input.value || '').trim());
      if (!Number.isInteger(target) || target < 1 || target > selectedOptionOrder.length) {
        input.focus();
        alert(`请输入 1 到 ${fmt(selectedOptionOrder.length)} 之间的整数。`);
        return;
      }
      moveSelectedOptionTo(input.dataset.cartPosition, target);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && document.getElementById('selectionDrawer').classList.contains('open')) {
        closeSelectionDrawer();
      }
      if (event.key === 'Escape' && document.getElementById('dataSourceWorkbench').classList.contains('open')) {
        closeDataSourceWorkbench();
      }
      if (event.key === 'Escape' && document.getElementById('settingsSlidePanel').classList.contains('open')) {
        closeSettingsSlide();
      }
      if (event.key === 'Escape' && document.getElementById('reportPreviewDialog').classList.contains('open')) {
        closeReportPreview();
      }
    });
    document.getElementById('matchedUniversityRows').addEventListener('click', event => {
      const button = event.target.closest('button[data-action]');
      if (!button) return;
      if (button.dataset.action === 'remove-selected' && button.dataset.optionKey) {
        removeSelectedOption(button.dataset.optionKey);
        syncRecommendationsFromSelection();
        renderMatchedUniversityRows();
        return;
      }
      if (button.dataset.action === 'toggle-selected' && button.dataset.optionKey) {
        if (selectedOptionKeys.has(button.dataset.optionKey)) {
          removeSelectedOption(button.dataset.optionKey);
        } else {
          addSelectedOption(button.dataset.optionKey);
        }
        syncRecommendationsFromSelection();
        renderMatchedUniversityRows();
        renderSelectionCart();
      }
    });
    document.getElementById('matchedUniversityRows').addEventListener('change', event => {
      const input = event.target.closest('input[data-option-key]');
      if (!input) return;
      if (input.checked) addSelectedOption(input.dataset.optionKey);
      else removeSelectedOption(input.dataset.optionKey);
      syncRecommendationsFromSelection();
      renderMatchedUniversityRows();
    });
    addListener('autoSortVolunteers', 'click', autoSortVolunteers);
    addListener('matchedPagination', 'click', handlePaginationClick);
    addListener('matchedPagination', 'keydown', handlePaginationJumpKeydown);
    addListener('matchedPagination', 'change', handlePaginationSizeChange);
    addListener('recommendationPagination', 'click', handlePaginationClick);
    addListener('recommendationPagination', 'keydown', handlePaginationJumpKeydown);
    addListener('recommendationPagination', 'change', handlePaginationSizeChange);
    document.querySelectorAll('[data-step-tab]').forEach(button => {
      button.addEventListener('click', () => setActiveStep(button.dataset.stepTab));
    });
    document.getElementById('candidateSearch').addEventListener('input', event => {
      candidateSearchText = event.target.value;
      matchedPage = 1;
      renderMatchedUniversityRows();
    });
    document.getElementById('clearCandidateSearch').addEventListener('click', () => {
      candidateSearchText = '';
      matchedPage = 1;
      document.getElementById('candidateSearch').value = '';
      renderMatchedUniversityRows();
    });
    document.getElementById('freeSelectionToggle').addEventListener('change', event => {
      freeSelectionMode = event.target.checked;
      if (freeSelectionMode && candidateRiskFilter !== 'selected') candidateRiskFilter = 'all';
      matchedPage = 1;
      renderMatchedUniversityRows();
    });
    document.getElementById('clearSelectedCandidates').addEventListener('click', () => {
      clearSelectedCart();
    });
    document.getElementById('matchedFilters').addEventListener('click', event => {
      const button = event.target.closest('button[data-risk-filter]');
      if (!button) return;
      candidateRiskFilter = button.dataset.riskFilter;
      matchedPage = 1;
      renderMatchedUniversityRows();
    });
    document.getElementById('strategyCompareCards').addEventListener('click', event => {
      if (event.target.closest('input, button, a, label, .help-icon')) return;
      const card = event.target.closest('[data-strategy-card]');
      if (!card) return;
      if (card.dataset.strategyCard === currentStrategy()) return;
      setStrategy(card.dataset.strategyCard);
    });
    document.getElementById('strategyCompareCards').addEventListener('input', event => {
      const input = event.target.closest('input[data-custom-count], input[data-custom-gap-number]');
      if (!input) return;
      const previous = currentStrategy();
      if (form.elements.strategy) form.elements.strategy.value = 'custom';
      if (input.matches('[data-custom-gap-number]')) customGapNumbers = customGapNumberValues();
      if (input.matches('[data-custom-count]')) applyCustomGroupCountsToQuotas(true);
      syncStrategyDescription();
      syncCustomStrategyCardPreview();
      renderSelectionCart();
      document.querySelectorAll('[data-strategy-card]').forEach(card => {
        card.classList.toggle('active', card.dataset.strategyCard === 'custom');
        card.setAttribute('aria-pressed', card.dataset.strategyCard === 'custom' ? 'true' : 'false');
        const chip = card.querySelector('.strategy-select-chip');
        if (chip) chip.textContent = card.dataset.strategyCard === 'custom' ? '已选' : '点击选择';
      });
      markSettingsDirty(previous === 'custom' ? '已调整自定义方案设定，请重新使用生成方案功能' : '已切换为自定义方案，请重新使用生成方案功能');
    });
    document.getElementById('strategyCompareCards').addEventListener('change', event => {
      if (!event.target.closest('input[data-custom-count], input[data-custom-gap-number]')) return;
      if (event.target.closest('input[data-custom-count]')) applyCustomGroupCountsToQuotas(true);
      if (event.target.closest('input[data-custom-gap-number]')) customGapNumbers = customGapNumberValues();
      renderStrategyComparison(latestPlanData);
    });
    document.getElementById('strategyCompareCards').addEventListener('keydown', event => {
      if (!['Enter', ' '].includes(event.key) || event.target.closest('input, button, a')) return;
      const card = event.target.closest('[data-strategy-card]');
      if (!card) return;
      event.preventDefault();
      if (card.dataset.strategyCard !== currentStrategy()) setStrategy(card.dataset.strategyCard);
    });
    document.getElementById('subjectButton').addEventListener('click', openSubjectDialog);
    document.getElementById('subjectClose').addEventListener('click', closeSubjectDialog);
    document.getElementById('subjectReset').addEventListener('click', () => {
      selectedSubjects = [];
      syncSubjects();
      renderSubjectDialog();
      document.getElementById('subjectError').textContent = '请选择 3 门。';
      markSettingsDirty();
    });
    document.getElementById('subjectConfirm').addEventListener('click', () => {
      if (selectedSubjects.length !== 3) {
        document.getElementById('subjectError').textContent = '必须选择 3 门后才能确认。';
        return;
      }
      syncSubjects();
      closeSubjectDialog();
      markSettingsDirty();
    });
    document.getElementById('subjectDialog').addEventListener('click', event => {
      if (event.target.id === 'subjectDialog') closeSubjectDialog();
    });
    document.getElementById('interestPickerButton').addEventListener('click', openInterestPickerDialog);
    document.getElementById('interestPickerClose').addEventListener('click', closeInterestPickerDialog);
    document.getElementById('interestPickerDialog').addEventListener('click', event => {
      if (event.target.id === 'interestPickerDialog') closeInterestPickerDialog();
    });
    document.getElementById('interestSearch').addEventListener('input', renderInterestOptions);
    document.getElementById('interestPickerClear').addEventListener('click', () => {
      if (!confirm('确定要清空已选择的专业吗？')) return;
      selectedInterests = [];
      syncInterests();
      renderInterestOptions();
      renderMajorSelector();
      document.getElementById('interestPickerError').textContent = '已清空专业选择，系统将默认不限制专业范围。';
      markSettingsDirty();
    });
    document.getElementById('interestPickerConfirm').addEventListener('click', () => {
      syncInterests();
      closeInterestPickerDialog();
      markSettingsDirty();
    });
    document.getElementById('interestTestButton').addEventListener('click', openInterestDialog);
    document.getElementById('interestClose').addEventListener('click', closeInterestDialog);
    document.getElementById('interestDialog').addEventListener('click', event => {
      if (event.target.id === 'interestDialog') closeInterestDialog();
    });
    document.getElementById('interestClear').addEventListener('click', () => {
      interestAnswers = {};
      generatedInterestKeywords = [];
      document.getElementById('interestResult').classList.remove('open');
      document.getElementById('interestResult').innerHTML = '';
      document.getElementById('interestError').textContent = '';
      renderInterestQuestions();
    });
    document.getElementById('interestCalculate').addEventListener('click', calculateInterestResult);
    document.getElementById('interestApply').addEventListener('click', () => {
      if (!generatedInterestKeywords.length) {
        calculateInterestResult();
        if (!generatedInterestKeywords.length) return;
      }
      setSelectedInterests(generatedInterestKeywords);
      closeInterestDialog();
      markSettingsDirty();
    });
    document.querySelectorAll('[data-info]').forEach(button => {
      button.addEventListener('click', () => openInfoDialog(button.dataset.info));
    });
    document.getElementById('infoDialogClose').addEventListener('click', closeInfoDialog);
    document.getElementById('infoDialog').addEventListener('click', event => {
      if (event.target.id === 'infoDialog') closeInfoDialog();
    });
    document.getElementById('reportPreviewClose').addEventListener('click', closeReportPreview);
    document.getElementById('reportPreviewDialog').addEventListener('click', event => {
      if (event.target.id === 'reportPreviewDialog') closeReportPreview();
    });
    document.getElementById('infoDialogBody').addEventListener('change', event => {
      if (event.target.id !== 'startupAgreementCheckbox') return;
      const confirmButton = document.getElementById('startupAgreementConfirm');
      if (confirmButton) confirmButton.disabled = !event.target.checked;
    });
    document.getElementById('infoDialogBody').addEventListener('click', event => {
      if (event.target.id === 'startupAgreementCancel') {
        cancelStartupAgreement();
      }
      if (event.target.id === 'startupAgreementConfirm') {
        const checkbox = document.getElementById('startupAgreementCheckbox');
        if (!checkbox || !checkbox.checked) return;
        acceptStartupAgreement();
      }
    });
    document.getElementById('previewReportButton').addEventListener('click', previewReport);
    document.getElementById('exportPdfButton').addEventListener('click', exportPdfReport);
    applyUrlParams();
    syncSubjects();
    syncInterests();
    syncCustomPlanPanel();
    syncProfileFilterSummary();
    renderStrategyComparison();
    syncSelectionCartLayout();
    setupHelpTooltips();
    startupReadyPromise = loadSystemInfo();
    showStartupCompliance();
  </script>
</body>
</html>
"""


def create_handler(db_path: Path):
    db_path = Path(db_path).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"数据库文件不存在：{db_path}")
    project_root = project_root_from(db_path)
    with connect(db_path) as connection:
        admissions = fetch_admissions(connection)
        score_ranks = fetch_score_ranks(connection)
        batches = list_batches(connection)
    if not admissions:
        raise RuntimeError(f"数据库没有招生记录：{db_path}")
    if not score_ranks:
        raise RuntimeError(f"数据库没有一分一段记录：{db_path}")
    majors_path = db_path.parent / "undergraduate_majors_2026.json"
    major_catalog = json.loads(majors_path.read_text(encoding="utf-8")) if majors_path.exists() else {
        "source": "未找到 2026 本科专业目录结构化数据。",
        "official_url": "",
        "count": 0,
        "majors": [],
    }
    major_catalog = _major_catalog_with_admission_names(major_catalog, admissions)
    official_2026_status = _load_official_2026_status(db_path)
    plan_2026_status = _plan_2026_status(db_path)
    backtest_summary = _backtest_summary(admissions)
    data_lineage = _data_lineage_payload(batches, major_catalog, plan_2026_status, official_2026_status)
    charter_registry = _load_charter_registry(db_path)
    plan_cache: dict[tuple[tuple[str, tuple[str, ...]], ...], dict] = {}

    def reload_runtime_data() -> None:
        nonlocal admissions, score_ranks, batches, major_catalog, official_2026_status
        nonlocal plan_2026_status, backtest_summary, data_lineage, charter_registry, plan_cache
        with connect(db_path) as connection:
            admissions = fetch_admissions(connection)
            score_ranks = fetch_score_ranks(connection)
            batches = list_batches(connection)
        majors_path = db_path.parent / "undergraduate_majors_2026.json"
        major_catalog = json.loads(majors_path.read_text(encoding="utf-8")) if majors_path.exists() else {
            "source": "未找到 2026 本科专业目录结构化数据。",
            "official_url": "",
            "count": 0,
            "majors": [],
        }
        major_catalog = _major_catalog_with_admission_names(major_catalog, admissions)
        official_2026_status = _load_official_2026_status(db_path)
        plan_2026_status = _plan_2026_status(db_path)
        backtest_summary = _backtest_summary(admissions)
        data_lineage = _data_lineage_payload(batches, major_catalog, plan_2026_status, official_2026_status)
        charter_registry = _load_charter_registry(db_path)
        plan_cache = {}

    class AppHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/index.html"}:
                self._send(200, APP_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
                return
            if parsed.path == "/api/system-info":
                payload = system_info_payload(project_root)
                payload["record_count"] = len(admissions)
                payload["score_rank_record_count"] = len(score_ranks)
                payload["data_lineage"] = data_lineage
                payload["plan_2026_status"] = plan_2026_status
                payload["official_2026_status"] = official_2026_status
                self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                return
            if parsed.path == "/api/data-sources":
                payload = _data_sources_payload(project_root, db_path)
                self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                return
            if parsed.path == "/api/data-sources/records":
                try:
                    query = parse_qs(parsed.query)
                    data_type = _str_arg(query, "type", default="")
                    year = _optional_int_arg(query, "year")
                    search = _str_arg(query, "q", default="")
                    page = _bounded_int_arg(query, "page", default=1, minimum=1, maximum=100000)
                    page_size = _bounded_int_arg(query, "page_size", default=25, minimum=10, maximum=100)
                    payload = _data_source_records_payload(project_root, db_path, data_type, year, search, page, page_size)
                except Exception as exc:
                    self._send(400, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                    return
                self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                return
            if parsed.path == "/api/data-sources/template":
                try:
                    query = parse_qs(parsed.query)
                    body, content_type, filename = _template_response(_str_arg(query, "type", default="admission_plan"))
                except Exception as exc:
                    self._send(400, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                    return
                self._send(
                    200,
                    body,
                    content_type,
                    {
                        "Content-Disposition": f'attachment; filename="{filename}"',
                    },
                )
                return
            if parsed.path == "/api/data-sources/export":
                try:
                    query = parse_qs(parsed.query)
                    data_type = _str_arg(query, "type", default="")
                    year = _optional_int_arg(query, "year")
                    body, content_type, filename = _export_data_source(project_root, db_path, data_type, year)
                except Exception as exc:
                    self._send(400, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                    return
                self._send(
                    200,
                    body,
                    content_type,
                    {
                        "Content-Disposition": f'attachment; filename="{filename}"',
                    },
                )
                return
            if parsed.path in {"/api/plan", "/plan.json", "/plan-data"}:
                try:
                    payload = self._build_plan(parse_qs(parsed.query))
                except Exception as exc:
                    self._send(400, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                    return
                self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                return
            if parsed.path in {"/api/majors", "/majors.json", "/majors-data"}:
                self._send(200, json.dumps(major_catalog, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                return
            self._send(404, b"Not found", "text/plain")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length else b""
            if parsed.path == "/api/data-sources/upload":
                try:
                    item = _save_uploaded_data_source(project_root, self.headers.get("Content-Type", ""), body)
                except Exception as exc:
                    self._send(400, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                    return
                self._send(200, json.dumps({"ok": True, "item": item}, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                return
            if parsed.path == "/api/data-sources/import":
                try:
                    result = _import_data_source(project_root, db_path, self.headers.get("Content-Type", ""), body)
                    reload_runtime_data()
                except Exception as exc:
                    self._send(400, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                    return
                self._send(200, json.dumps({"ok": True, **result}, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                return
            if parsed.path == "/api/data-sources/years/create":
                try:
                    payload = json.loads(body.decode("utf-8") or "{}")
                    result = _create_data_source_year(project_root, payload, _database_year_items(db_path))
                except Exception as exc:
                    self._send(400, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                    return
                self._send(200, json.dumps({"ok": True, **result}, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                return
            if parsed.path == "/api/data-sources/delete":
                try:
                    payload = json.loads(body.decode("utf-8") or "{}")
                    result = _delete_data_source(project_root, db_path, payload)
                    reload_runtime_data()
                except Exception as exc:
                    self._send(400, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                    return
                self._send(200, json.dumps({"ok": True, **result}, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                return
            if parsed.path == "/api/data-sources/records/update":
                try:
                    payload = json.loads(body.decode("utf-8") or "{}")
                    result = _update_data_source_record(project_root, db_path, payload)
                    reload_runtime_data()
                except Exception as exc:
                    self._send(400, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                    return
                self._send(200, json.dumps({"ok": True, **result}, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                return
            self._send(404, b"Not found", "text/plain")

        def log_message(self, format: str, *args) -> None:
            return

        def _build_plan(self, query: dict[str, list[str]]) -> dict:
            cache_key = tuple(sorted((key, tuple(value)) for key, value in query.items()))
            if cache_key in plan_cache:
                return plan_cache[cache_key]
            rank = _int_arg(query, "rank", required=True)
            if rank <= 0:
                raise ValueError("全省位次必须是正整数。")
            band_width = _bounded_int_arg(query, "band_width", default=20, minimum=0, maximum=80)
            target_size = _bounded_int_arg(query, "target_size", default=96, minimum=1, maximum=150)
            strategy = _str_arg(query, "strategy", default="balanced")
            custom_quotas = _custom_quotas_arg(query)
            custom_risk_gaps = _custom_risk_gaps_arg(query)
            if strategy == "custom":
                if not custom_quotas:
                    raise ValueError("自定义方案至少需要设置 1 个志愿数量。")
                target_size = sum(custom_quotas.values())
                if target_size > 150:
                    raise ValueError("自定义方案数量不能超过 150。")
            max_tuition = _bounded_optional_int_arg(query, "max_tuition", minimum=0, maximum=200000)
            subjects = tuple(_list_arg(query, "subjects"))
            if len(subjects) != 3:
                raise ValueError("选科必须且只能选择 3 门。")
            candidate = CandidateProfile(
                score=0,
                rank=rank,
                subjects=subjects,
                interests=tuple(_list_arg(query, "interests")),
                avoid_keywords=tuple(_list_arg(query, "avoid_keywords")),
                max_tuition=max_tuition,
                preferred_cities=tuple(_list_arg(query, "preferred_cities")),
                blocked_cities=tuple(_list_arg(query, "blocked_cities")),
                allow_private=_bool_arg(query, "allow_private"),
                allow_sino_foreign=_bool_arg(query, "allow_sino_foreign"),
                require_known_subjects=_bool_arg(query, "require_known_subjects"),
                require_double_first_class=_bool_arg(query, "require_double_first_class"),
                require_985=_bool_arg(query, "require_985"),
                require_211=_bool_arg(query, "require_211"),
                require_public_undergraduate=_bool_arg(query, "require_public_undergraduate"),
            )
            result = build_score_band_plan(
                admissions,
                score_ranks,
                rank,
                candidate,
                strategy=strategy,
                target_size=target_size,
                band_width=band_width,
                custom_quotas=custom_quotas,
                custom_risk_gaps=custom_risk_gaps,
            )
            plan = result.plan
            plan_results = {strategy: plan}
            base_recommendations = list(result.candidate_recommendations)
            base_rejections = list(plan.rejections)
            for compare_strategy in ("conservative", "balanced", "aggressive"):
                if compare_strategy not in plan_results:
                    plan_results[compare_strategy] = build_volunteer_plan_from_recommendations(
                        base_recommendations,
                        base_rejections,
                        candidate=candidate,
                        strategy=compare_strategy,
                        target_size=target_size,
                    )
            if custom_quotas and "custom" not in plan_results:
                plan_results["custom"] = build_volunteer_plan_from_recommendations(
                    base_recommendations,
                    base_rejections,
                    candidate=candidate,
                    strategy="custom",
                    target_size=sum(custom_quotas.values()),
                    custom_quotas=custom_quotas,
                )
            recommendations_payload = [
                payload
                for item in plan.recommendations
                for payload in [_recommendation_payload(item, charter_registry)]
                if not _is_2026_stopped_option(payload)
            ]
            candidate_recommendations_payload = [
                payload
                for item in result.candidate_recommendations
                for payload in [_recommendation_payload(item, charter_registry)]
                if not _is_2026_stopped_option(payload)
            ]
            search_recommendations_payload = [
                payload
                for item in result.search_recommendations
                for payload in [_recommendation_payload(item, charter_registry, compact=True)]
                if not _is_2026_stopped_option(payload)
            ]
            edge_case_warnings = _edge_case_warnings(rank, candidate, score_ranks)
            payload = {
                "app_version": SERVER_APP_VERSION,
                "system_info": system_info_payload(project_root),
                "candidate": asdict(candidate),
                "record_count": len(admissions),
                "score_rank_record_count": len(score_ranks),
                "batches": batches,
                "data_lineage": data_lineage,
                "official_2026_status": official_2026_status,
                "equivalent_scores": [asdict(item) for item in result.equivalent_scores],
                "band_matches": [asdict(item) for item in result.band_matches],
                "plan_2026_status": plan_2026_status,
                "backtest_summary": backtest_summary,
                "edge_case_warnings": edge_case_warnings,
                "commercial_readiness": _commercial_readiness_payload(
                    plan_2026_status,
                    backtest_summary,
                    recommendations_payload,
                    edge_case_warnings,
                    major_catalog,
                ),
                "compliance": _compliance_payload(),
                "strategy_compare": {
                    key: _strategy_compare_payload(key, value)
                    for key, value in plan_results.items()
                },
                "plan": {
                    "strategy": plan.strategy,
                    "target_size": plan.target_size,
                    "quotas": plan.quotas,
                    "risk_counts": plan.risk_counts,
                    "warnings": plan.warnings,
                    "recommendations": recommendations_payload,
                    "candidate_recommendations": candidate_recommendations_payload,
                    "search_recommendations": search_recommendations_payload,
                    "score_band_candidate_count": result.score_band_candidate_count,
                    "coverage_guard_added": result.coverage_guard_added,
                    "custom_risk_gaps": custom_risk_gaps if strategy == "custom" else None,
                    "rejections_total": len(plan.rejections),
                },
            }
            plan_cache[cache_key] = payload
            if len(plan_cache) > 24:
                oldest_key = next(iter(plan_cache))
                plan_cache.pop(oldest_key, None)
            return payload

        def _send(self, status: int, body: bytes, content_type: str, extra_headers: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return AppHandler


def _major_catalog_with_admission_names(major_catalog: dict, admissions: list) -> dict:
    payload = dict(major_catalog or {})
    rows: dict[str, dict[str, object]] = {}
    for record in admissions:
        name = str(getattr(record, "major_name", "") or "").strip()
        if not name:
            continue
        entry = rows.setdefault(
            name,
            {
                "name": name,
                "latest_year": int(getattr(record, "year", 0) or 0),
                "count": 0,
                "years": set(),
                "source": "山东省普通类常规批投档表专业名称",
                "kind": "admission",
            },
        )
        entry["count"] = int(entry.get("count") or 0) + 1
        entry["latest_year"] = max(int(entry.get("latest_year") or 0), int(getattr(record, "year", 0) or 0))
        years = entry.get("years")
        if isinstance(years, set):
            years.add(int(getattr(record, "year", 0) or 0))

    admission_names = []
    for entry in rows.values():
        years = sorted(year for year in entry.get("years", set()) if year)
        admission_names.append(
            {
                "name": entry["name"],
                "latest_year": entry["latest_year"],
                "count": entry["count"],
                "years": years,
                "source": entry["source"],
                "kind": entry["kind"],
            }
        )
    admission_names.sort(key=lambda item: (-int(item["latest_year"]), -int(item["count"]), str(item["name"])))
    payload["admission_major_names"] = admission_names
    payload["admission_major_count"] = len(admission_names)
    payload["selection_source"] = "教育部《普通高等学校本科专业目录（2026年）》标准专业名称 + 山东省普通类常规批投档表招生专业名称"
    return payload


DATA_SOURCE_TEMPLATES = {
    "admission": {
        "filename": "admission_records_template.csv",
        "label": "历年招录/招生计划模板",
        "content": (
            "year,source_id,school_code,school_name,major_code,major_name,min_score,min_rank,plan_count,subjects,province,city,school_level,school_type,tuition,tags\n"
            "2025,sdzk_2025_regular_batch_round1,A000,样例大学,01,样例专业,600,30000,10,物理|化学,山东,济南,本科,公办,5000,示例\n"
        ),
    },
    "score_rank": {
        "filename": "score_rank_template.csv",
        "label": "一分一段表模板",
        "content": (
            "year,source_id,score,segment_count,cumulative_count,subject_group\n"
            "2026,sdzk_2026_summer_score_rank,600,1200,30000,全体\n"
        ),
    },
    "major_catalog": {
        "filename": "major_catalog_template.json",
        "label": "专业目录模板",
        "content": (
            '{\n'
            '  "source": "教育部《普通高等学校本科专业目录》",\n'
            '  "official_url": "https://example.com",\n'
            '  "count": 1,\n'
            '  "majors": [{"code": "080902", "name": "软件工程", "discipline": "工学", "category": "计算机类"}]\n'
            '}\n'
        ),
    },
    "interest_map": {
        "filename": "interest_major_map_template.json",
        "label": "专业标签映射模板",
        "content": (
            '{\n'
            '  "version": "interest-major-map-v1",\n'
            '  "interests": {"计算机类": ["软件工程", "计算机科学与技术"]}\n'
            '}\n'
        ),
    },
    "plan_supplement": {
        "filename": "official_plan_supplement_template.csv",
        "label": "官方招生计划补充模板",
        "content": (
            "batch,school_code,school_name,major_code,major_name,action,plan_count_2026,tuition_2026,note,source,source_url,source_id,source_type,confidence,published_at,updated_at\n"
            "普通类常规批,A000,样例大学,01,样例专业,plan_adjusted,10,,计划数调整为10,山东省教育招生考试院,https://example.com,source_id,official_supplement,official,2026-06-27,2026-06-30\n"
        ),
    },
    "discipline_quality": {
        "filename": "discipline_quality_template.csv",
        "label": "学科评价模板",
        "content": (
            "school_name,major_keywords,discipline,assessment_grade,postgraduate_recommend_rate,source,source_url,updated_at,assessment_round,discipline_code,source_id,source_type,confidence,note\n"
            "样例大学,计算机类|软件工程,计算机科学与技术,A,12.5,学校官网,https://example.com,2026-06-30,第五轮,0812,source_id,school_disclosure,school_confirmed,示例\n"
        ),
    },
    "postgraduate_rates": {
        "filename": "postgraduate_rates_template.csv",
        "label": "保研率模板",
        "content": (
            "rank,school_level,school_name,school_aliases,cohort,recommend_quota,postgraduate_recommend_rate,rate_display,source,source_url,source_id,source_type,confidence,updated_at,note\n"
            "1,985,样例大学,样例大学,2025届,100,12.5,12.5%,学校官网,https://example.com,source_id,school_disclosure,school_confirmed,2026-06-30,示例\n"
        ),
    },
    "school_info": {
        "filename": "school_info_template.json",
        "label": "高校信息/章程索引模板",
        "content": (
            '{\n'
            '  "updated_at": "2026-06-30",\n'
            '  "schools": {"样例大学": {"source_url": "https://example.com", "city": "济南", "tags": ["公办本科"]}}\n'
            '}\n'
        ),
    },
}


DATA_SOURCE_CATEGORIES = {
    "admission": "历史招录/计划",
    "score_rank": "一分一段",
    "major_catalog": "专业目录",
    "interest_map": "专业标签",
    "plan_supplement": "招生计划补充",
    "discipline_quality": "学科评估/保研率",
    "postgraduate_rates": "保研率",
    "school_info": "高校信息/章程",
    "official_status": "官方状态核验",
    "other": "其他",
}


MANAGED_FILE_DATASETS = {
    "major_catalog": {
        "name": "专业目录",
        "path": "data/processed/undergraduate_majors_2026.json",
        "extensions": {".json"},
    },
    "interest_map": {
        "name": "专业标签映射",
        "path": "data/processed/interest_major_map.json",
        "extensions": {".json"},
    },
    "plan_supplement": {
        "name": "招生计划补充",
        "path": "data/curated/official_2026_plan_supplements.csv",
        "extensions": {".csv"},
    },
    "discipline_quality": {
        "name": "学科评价",
        "path": "data/curated/discipline_quality.csv",
        "extensions": {".csv"},
    },
    "postgraduate_rates": {
        "name": "保研率",
        "path": "data/curated/postgraduate_recommend_rates.csv",
        "extensions": {".csv"},
    },
    "school_info": {
        "name": "高校信息/章程索引",
        "path": "data/processed/charter_registry_2026.json",
        "extensions": {".json"},
    },
    "official_status": {
        "name": "官方状态核验",
        "path": "data/processed/official_2026_status.json",
        "extensions": {".json"},
    },
}

DATA_SOURCE_CURRENT_YEAR = 2026
DATA_SOURCE_REQUIRED_YEARS = [2023, 2024, 2025, 2026]
DATA_SOURCE_YEAR_CONFIG = "data/processed/data_source_years.json"

YEARLY_DATA_REQUIREMENTS = [
    {
        "category": "admission",
        "name": "历史招录/招生计划",
        "scope": "all",
        "required": True,
        "description": "该年度院校专业计划、最低分和最低位次，是推荐和回溯的核心数据。",
    },
    {
        "category": "score_rank",
        "name": "一分一段表",
        "scope": "all",
        "required": True,
        "description": "该年度分数和位次换算数据，用于不同年份之间的等效分参考。",
    },
    {
        "category": "plan_supplement",
        "name": "招生计划补充",
        "scope": "current",
        "required": True,
        "description": "当前填报年度官方补充、撤销、调整等计划变更。",
    },
    {
        "category": "official_status",
        "name": "官方状态核验",
        "scope": "current",
        "required": True,
        "description": "当前填报年度官方页面、附件和导入状态核验。",
    },
    {
        "category": "major_catalog",
        "name": "专业目录",
        "scope": "current",
        "required": True,
        "description": "当前填报年度专业目录与标准专业口径。",
    },
    {
        "category": "interest_map",
        "name": "专业标签映射",
        "scope": "current",
        "required": True,
        "description": "当前年度专业选择、兴趣标签和招生专业名称映射。",
    },
    {
        "category": "discipline_quality",
        "name": "学科评价",
        "scope": "current",
        "required": True,
        "description": "院校学科评价、评估轮次和来源依据。",
    },
    {
        "category": "postgraduate_rates",
        "name": "保研率",
        "scope": "current",
        "required": True,
        "description": "院校保研率、届别、来源和可信度说明。",
    },
    {
        "category": "school_info",
        "name": "高校信息/章程索引",
        "scope": "current",
        "required": True,
        "description": "当前年度高校章程、来源链接和核验摘要。",
    },
]


def _data_source_year_config_path(root: Path) -> Path:
    return root / DATA_SOURCE_YEAR_CONFIG


def _load_data_source_year_config(root: Path) -> dict[str, object]:
    path = _data_source_year_config_path(root)
    if not path.exists():
        return {"years": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"years": []}
    return payload if isinstance(payload, dict) else {"years": []}


def _write_data_source_year_config(root: Path, payload: dict[str, object]) -> None:
    path = _data_source_year_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _custom_data_source_years(root: Path) -> list[int]:
    payload = _load_data_source_year_config(root)
    years: list[int] = []
    for item in payload.get("years", []):
        try:
            years.append(int(item))
        except (TypeError, ValueError):
            continue
    return years


def _create_data_source_year(root: Path, payload: dict[str, object], database_items: list[dict[str, object]] | None = None) -> dict[str, object]:
    try:
        year = int(payload.get("year") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("年度格式不正确。") from exc
    if year < 2020 or year > 2035:
        raise ValueError("年度必须在 2020-2035 之间。")
    config = _load_data_source_year_config(root)
    years = set(_custom_data_source_years(root))
    years.add(year)
    config["years"] = sorted(years)
    config["last_created_year"] = year
    config["copy_previous"] = bool(payload.get("copy_previous", True))
    if payload.get("base_year"):
        config["last_base_year"] = int(payload.get("base_year"))
    _write_data_source_year_config(root, config)
    return {
        "created": True,
        "year": year,
        "years": _data_source_required_years(root, database_items),
        "config_path": DATA_SOURCE_YEAR_CONFIG,
    }


DATA_RECORD_LABELS = {
    "id": "ID",
    "import_batch_id": "导入批次",
    "year": "年度",
    "source_id": "来源ID",
    "school_code": "院校代码",
    "school_name": "院校名称",
    "major_code": "专业代码",
    "major_name": "专业名称",
    "min_score": "最低分",
    "min_rank": "最低位次",
    "plan_count": "计划数",
    "subjects": "选科要求",
    "province": "省份",
    "city": "城市",
    "school_level": "院校层次",
    "school_type": "办学性质",
    "tuition": "学费",
    "tags": "标签",
    "option_key": "系统键",
    "score": "分数",
    "segment_count": "本段人数",
    "cumulative_count": "累计人数",
    "subject_group": "科类",
    "discipline": "学科门类",
    "category": "专业类",
    "code": "专业代码",
    "name": "名称",
    "major_keywords": "专业关键词",
    "assessment_grade": "学科评估",
    "postgraduate_recommend_rate": "保研率",
    "assessment_round": "评估轮次",
    "discipline_code": "学科代码",
    "source": "来源",
    "source_url": "来源链接",
    "source_type": "来源类型",
    "confidence": "可信度",
    "updated_at": "更新时间",
    "note": "备注",
    "rank": "排名",
    "school_aliases": "学校别名",
    "cohort": "届别",
    "recommend_quota": "推免名额",
    "rate_display": "保研率展示",
    "batch": "批次",
    "action": "动作",
    "plan_count_2026": "2026计划数",
    "tuition_2026": "2026学费",
    "published_at": "发布时间",
    "major_name_key": "专业名称",
    "direct": "直接标签",
    "related": "相关标签",
    "school_name_key": "学校名称",
    "aliases": "别名",
    "checked_at": "核验时间",
    "status": "状态",
    "source_title": "来源标题",
    "summary": "摘要",
    "item_key": "项目",
    "kind": "类别",
    "page_url": "页面链接",
    "title": "标题",
    "found": "是否找到",
}

DATABASE_RECORD_DATASETS = {
    "admission": {
        "table": "admission_records",
        "label": DATA_SOURCE_CATEGORIES["admission"],
        "columns": [
            "id",
            "import_batch_id",
            "year",
            "source_id",
            "school_code",
            "school_name",
            "major_code",
            "major_name",
            "min_score",
            "min_rank",
            "plan_count",
            "subjects",
            "province",
            "city",
            "school_level",
            "school_type",
            "tuition",
            "tags",
            "option_key",
        ],
        "readonly": {"id", "import_batch_id", "option_key"},
        "integer": {"year", "min_score", "min_rank", "plan_count", "tuition"},
        "search": ["source_id", "school_code", "school_name", "major_code", "major_name", "subjects", "province", "city", "tags"],
        "order": "school_code, major_code, major_name, id",
    },
    "score_rank": {
        "table": "score_rank_records",
        "label": DATA_SOURCE_CATEGORIES["score_rank"],
        "columns": ["id", "import_batch_id", "year", "source_id", "score", "segment_count", "cumulative_count", "subject_group"],
        "readonly": {"id", "import_batch_id"},
        "integer": {"year", "score", "segment_count", "cumulative_count"},
        "search": ["source_id", "subject_group", "score", "cumulative_count"],
        "order": "score DESC, id",
    },
}

JSON_RECORD_DATASETS = {
    "major_catalog": {
        "collection": "majors",
        "kind": "list",
        "key_label": "",
        "columns": ["discipline", "category", "code", "name"],
        "readonly": set(),
    },
    "interest_map": {
        "collection": "majors",
        "kind": "dict",
        "key_label": "major_name_key",
        "columns": ["major_name_key", "direct", "related"],
        "readonly": {"major_name_key"},
        "list_fields": {"direct", "related"},
    },
    "school_info": {
        "collection": "schools",
        "kind": "dict",
        "key_label": "school_name_key",
        "columns": [
            "school_name_key",
            "matched_school",
            "school_id",
            "status",
            "checked_at",
            "source_type",
            "source_title",
            "source_url",
            "official_school_url",
            "summary",
            "aliases",
        ],
        "readonly": {"school_name_key"},
        "list_fields": {"aliases"},
    },
    "official_status": {
        "collection": "items",
        "kind": "dict",
        "key_label": "item_key",
        "columns": ["item_key", "source_id", "kind", "title", "found", "published_at", "page_url"],
        "readonly": {"item_key"},
    },
}


def _data_source_category(path: str) -> str:
    lower = path.replace("\\", "/").lower()
    if "score_rank" in lower or "一分一段" in lower:
        return "score_rank"
    if "regular_batch" in lower or "admission" in lower or "plan" in lower:
        return "admission"
    if "undergraduate_majors" in lower:
        return "major_catalog"
    if "interest" in lower:
        return "interest_map"
    if "official_2026_plan_supplements" in lower:
        return "plan_supplement"
    if "postgraduate" in lower:
        return "postgraduate_rates"
    if "discipline" in lower or "postgraduate" in lower:
        return "discipline_quality"
    if "charter" in lower:
        return "school_info"
    if "official_2026_status" in lower or "sources" in lower or "manifest" in lower:
        return "official_status"
    return "other"


def _data_source_label(path: str) -> str:
    labels = {
        "data/processed/official.sqlite": "2023-2025 招录与一分一段 SQLite 主库",
        "data/processed/undergraduate_majors_2026.json": "教育部 2026 本科专业目录",
        "data/processed/interest_major_map.json": "专业兴趣标签映射",
        "data/processed/charter_registry_2026.json": "2026 招生章程索引",
        "data/processed/official_2026_status.json": "2026 官方公开数据状态核验",
        "data/curated/discipline_quality.csv": "学科评估清单",
        "data/curated/postgraduate_recommend_rates.csv": "保研率清单",
        "data/curated/official_2026_plan_supplements.csv": "2026 官方招生计划补充信息",
    }
    return labels.get(path, Path(path).name)


def _user_source_dir(root: Path) -> Path:
    return root / "data" / "uploads" / "user_sources"


def _user_source_manifest_path(root: Path) -> Path:
    return _user_source_dir(root) / "manifest.json"


def _load_user_source_manifest(root: Path) -> list[dict[str, object]]:
    path = _user_source_manifest_path(root)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        rows = payload.get("items", [])
    else:
        rows = payload
    return [item for item in rows if isinstance(item, dict)]


def _write_user_source_manifest(root: Path, items: list[dict[str, object]]) -> None:
    path = _user_source_manifest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "items": items,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_upload_filename(filename: str) -> str:
    name = Path(filename or "upload.csv").name
    name = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", name).strip("._")
    return name[:120] or "upload.csv"


def _managed_file_path(data_type: str, year: int | None = None) -> str:
    config = MANAGED_FILE_DATASETS.get(data_type)
    if not config:
        raise ValueError("未知基础文件类型。")
    if not year or year == DATA_SOURCE_CURRENT_YEAR:
        return str(config["path"])
    dynamic_paths = {
        "major_catalog": f"data/processed/undergraduate_majors_{year}.json",
        "interest_map": f"data/processed/interest_major_map_{year}.json",
        "plan_supplement": f"data/curated/official_{year}_plan_supplements.csv",
        "discipline_quality": f"data/curated/discipline_quality_{year}.csv",
        "postgraduate_rates": f"data/curated/postgraduate_recommend_rates_{year}.csv",
        "school_info": f"data/processed/charter_registry_{year}.json",
        "official_status": f"data/processed/official_{year}_status.json",
    }
    return dynamic_paths.get(data_type, str(config["path"]))


def _managed_file_item(root: Path, data_type: str, config: dict[str, object], year: int | None = None) -> dict[str, object]:
    relative = _managed_file_path(data_type, year)
    path = root / relative
    exists = path.exists()
    return {
        "id": f"file:{data_type}:{year}" if year else f"file:{data_type}",
        "name": f"{year} {config['name']}" if year else str(config["name"]),
        "category": data_type,
        "category_label": DATA_SOURCE_CATEGORIES.get(data_type, DATA_SOURCE_CATEGORIES["other"]),
        "path": relative,
        "source_type": "managed_file",
        "source_type_label": "基础文件" if not year else "年度基础文件",
        "status": "已接入" if exists else "缺失",
        "size": path.stat().st_size if exists else 0,
        "sha256": _sha256_file(path) if exists else "",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime)) if exists else "",
        "year": year or "",
        "record_count": "",
        "importable": True,
        "exportable": exists,
        "deletable": exists,
        "record_viewable": exists,
    }


def _database_year_items(db_path: Path) -> list[dict[str, object]]:
    if not db_path or not db_path.exists():
        return []
    items: list[dict[str, object]] = []
    with connect(db_path) as connection:
        admission_rows = connection.execute(
            """
            SELECT year, COUNT(*) AS record_count, COUNT(DISTINCT school_code) AS school_count,
                   COUNT(DISTINCT option_key) AS option_count, MIN(min_rank) AS best_rank, MAX(min_rank) AS max_rank
            FROM admission_records
            GROUP BY year
            ORDER BY year
            """
        ).fetchall()
        score_rows = connection.execute(
            """
            SELECT year, COUNT(*) AS record_count, MIN(score) AS min_score, MAX(score) AS max_score,
                   MAX(cumulative_count) AS max_cumulative
            FROM score_rank_records
            GROUP BY year
            ORDER BY year
            """
        ).fetchall()
    for row in admission_rows:
        year = int(row["year"])
        items.append(
            {
                "id": f"db:admission:{year}",
                "name": f"{year} 历史招录/招生计划",
                "category": "admission",
                "category_label": DATA_SOURCE_CATEGORIES["admission"],
                "path": db_path.as_posix(),
                "source_type": "database",
                "source_type_label": "运行数据库",
                "status": "运行中",
                "year": year,
                "record_count": int(row["record_count"] or 0),
                "summary": f"{int(row['school_count'] or 0)} 所院校 / {int(row['option_count'] or 0)} 个专业项",
                "size": db_path.stat().st_size,
                "sha256": "",
                "importable": True,
                "exportable": True,
                "deletable": True,
                "record_viewable": True,
            }
        )
    for row in score_rows:
        year = int(row["year"])
        items.append(
            {
                "id": f"db:score_rank:{year}",
                "name": f"{year} 一分一段表",
                "category": "score_rank",
                "category_label": DATA_SOURCE_CATEGORIES["score_rank"],
                "path": db_path.as_posix(),
                "source_type": "database",
                "source_type_label": "运行数据库",
                "status": "运行中",
                "year": year,
                "record_count": int(row["record_count"] or 0),
                "summary": f"{row['min_score']}-{row['max_score']} 分 / 最大累计 {row['max_cumulative']}",
                "size": db_path.stat().st_size,
                "sha256": "",
                "importable": True,
                "exportable": True,
                "deletable": True,
                "record_viewable": True,
            }
        )
    return items


def _data_source_required_years(root: Path, database_items: list[dict[str, object]] | None = None) -> list[int]:
    years = set(DATA_SOURCE_REQUIRED_YEARS)
    years.update(_custom_data_source_years(root))
    for item in database_items or []:
        try:
            if item.get("year"):
                years.add(int(item["year"]))
        except (TypeError, ValueError):
            continue
    years.add(DATA_SOURCE_CURRENT_YEAR)
    return sorted(years)


def _data_source_current_year(root: Path, database_items: list[dict[str, object]] | None = None) -> int:
    years = _data_source_required_years(root, database_items)
    return max(years) if years else DATA_SOURCE_CURRENT_YEAR


def _year_requirement_applies(requirement: dict[str, object], year: int) -> bool:
    scope = str(requirement.get("scope") or "all")
    if scope == "current":
        return year >= DATA_SOURCE_CURRENT_YEAR
    if scope == "historical":
        return year < DATA_SOURCE_CURRENT_YEAR
    return True


def _yearly_data_source_items(
    root: Path,
    db_path: Path | None,
    database_items: list[dict[str, object]],
    managed_files: list[dict[str, object]],
) -> list[dict[str, object]]:
    database_by_key = {
        (str(item.get("category") or ""), int(item.get("year") or 0)): item
        for item in database_items
        if item.get("category") and item.get("year")
    }
    rows: list[dict[str, object]] = []
    for year in _data_source_required_years(root, database_items):
        for requirement in YEARLY_DATA_REQUIREMENTS:
            if not _year_requirement_applies(requirement, year):
                continue
            category = str(requirement["category"])
            existing = database_by_key.get((category, year)) if category in DATABASE_RECORD_DATASETS else _managed_file_item(root, category, MANAGED_FILE_DATASETS[category], year=year)
            if existing and category not in DATABASE_RECORD_DATASETS and existing.get("status") == "缺失":
                existing = None
            source_kind = "database" if category in DATABASE_RECORD_DATASETS else "managed_file"
            if existing:
                row = {**existing}
                row["id"] = str(existing.get("id") or f"year:{year}:{category}")
                row["name"] = f"{year} {requirement['name']}"
                row["status"] = "已接入" if existing.get("status") != "缺失" else "待导入"
                row["record_viewable"] = bool(existing.get("record_viewable"))
                row["exportable"] = bool(existing.get("exportable"))
                row["deletable"] = bool(existing.get("deletable"))
            else:
                target_path = db_path.as_posix() if source_kind == "database" and db_path else ""
                if source_kind == "managed_file":
                    target_path = _managed_file_path(category, year)
                row = {
                    "id": f"year:{year}:{category}",
                    "name": f"{year} {requirement['name']}",
                    "category": category,
                    "category_label": DATA_SOURCE_CATEGORIES.get(category, DATA_SOURCE_CATEGORIES["other"]),
                    "path": target_path,
                    "source_type": source_kind,
                    "source_type_label": "年度数据库" if source_kind == "database" else "年度基础文件",
                    "status": "待导入",
                    "year": year,
                    "record_count": "",
                    "summary": "该年度固定需要的数据，尚未接入。",
                    "size": 0,
                    "sha256": "",
                    "updated_at": "",
                    "importable": True,
                    "exportable": False,
                    "deletable": False,
                    "record_viewable": False,
                }
            row["year"] = year
            row["required"] = bool(requirement.get("required", True))
            row["description"] = str(requirement.get("description") or "")
            rows.append(row)
    return rows


def _data_sources_payload(root: Path, db_path: Path | None = None) -> dict[str, object]:
    release_path = root / "data" / "release_info.json"
    built_in: list[dict[str, object]] = []
    if release_path.exists():
        try:
            release = json.loads(release_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            release = {}
        for item in release.get("files", []):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if not path:
                continue
            category = _data_source_category(path)
            built_in.append(
                {
                    "id": f"builtin:{path}",
                    "name": _data_source_label(path),
                    "category": category,
                    "category_label": DATA_SOURCE_CATEGORIES.get(category, DATA_SOURCE_CATEGORIES["other"]),
                    "path": path,
                    "source_type": "built_in",
                    "source_type_label": "内置数据",
                    "status": "已接入" if item.get("exists") else "缺失",
                    "size": item.get("size", 0),
                    "sha256": item.get("sha256", ""),
                    "updated_at": release.get("generated_at", ""),
                    "year": "",
                    "record_count": "",
                    "importable": False,
                    "exportable": False,
                    "deletable": False,
                    "record_viewable": False,
                }
            )
    managed_files = [
        _managed_file_item(root, data_type, config)
        for data_type, config in MANAGED_FILE_DATASETS.items()
    ]
    database_items = _database_year_items(db_path) if db_path else []
    yearly_items = _yearly_data_source_items(root, db_path, database_items, managed_files)
    uploads = []
    for item in _load_user_source_manifest(root):
        category = str(item.get("category") or "other")
        uploads.append(
            {
                **item,
                "category": category,
                "category_label": DATA_SOURCE_CATEGORIES.get(category, DATA_SOURCE_CATEGORIES["other"]),
                "source_type": "user_uploaded",
                "source_type_label": "用户上传",
                "status": "已上传，待导入",
                "year": item.get("year", ""),
                "record_count": "",
                "importable": True,
                "exportable": True,
                "deletable": True,
                "record_viewable": False,
            }
        )
    items = database_items + managed_files + uploads + built_in
    return {
        "categories": DATA_SOURCE_CATEGORIES,
        "templates": [
            {"key": key, "label": value["label"], "filename": value["filename"]}
            for key, value in DATA_SOURCE_TEMPLATES.items()
        ],
        "items": items,
        "yearly_items": yearly_items,
        "years": _data_source_required_years(root, database_items),
        "current_year": _data_source_current_year(root, database_items),
        "database_count": len(database_items),
        "managed_file_count": len(managed_files),
        "built_in_count": len(built_in),
        "upload_count": len(uploads),
    }


def _template_response(template_key: str) -> tuple[bytes, str, str]:
    item = DATA_SOURCE_TEMPLATES.get(template_key)
    if not item:
        raise ValueError("未知模板类型。")
    filename = str(item["filename"])
    content_type = "application/json; charset=utf-8" if filename.endswith(".json") else "text/csv; charset=utf-8"
    prefix = "" if filename.endswith(".json") else "\ufeff"
    body = (prefix + item["content"]).encode("utf-8")
    return body, content_type, filename


def _multipart_value(disposition: str, key: str) -> str:
    match = re.search(rf'{key}="([^"]*)"', disposition)
    return match.group(1) if match else ""


def _parse_multipart_form(content_type: str, body: bytes) -> tuple[dict[str, str], dict[str, object]]:
    match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type or "")
    boundary = (match.group(1) or match.group(2)).encode("utf-8") if match else b""
    if not boundary:
        raise ValueError("上传格式缺少 boundary。")
    fields: dict[str, str] = {}
    file_part: dict[str, object] = {}
    for raw_part in body.split(b"--" + boundary):
        part = raw_part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        header_blob, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = header_blob.decode("utf-8", errors="replace").split("\r\n")
        disposition = next((line for line in headers if line.lower().startswith("content-disposition:")), "")
        content_type_line = next((line for line in headers if line.lower().startswith("content-type:")), "")
        name = _multipart_value(disposition, "name")
        filename = _multipart_value(disposition, "filename")
        data = data.removesuffix(b"\r\n")
        if filename:
            file_part = {
                "field": name,
                "filename": filename,
                "content_type": content_type_line.split(":", 1)[-1].strip() if ":" in content_type_line else "",
                "data": data,
            }
        elif name:
            fields[name] = data.decode("utf-8", errors="replace").strip()
    if not file_part:
        raise ValueError("请选择要上传的数据文件。")
    return fields, file_part


def _save_uploaded_data_source(root: Path, content_type: str, body: bytes) -> dict[str, object]:
    if len(body) > 25 * 1024 * 1024:
        raise ValueError("上传文件不能超过 25MB。")
    fields, file_part = _parse_multipart_form(content_type, body)
    raw_data = file_part.get("data")
    if not isinstance(raw_data, bytes) or not raw_data:
        raise ValueError("上传文件为空。")
    original_name = _safe_upload_filename(str(file_part.get("filename") or "upload.csv"))
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls", ".json", ".pdf", ".docx", ".html", ".htm"}:
        raise ValueError("仅支持 csv、xlsx、xls、json、pdf、docx、html 文件。")
    category = fields.get("category", "other")
    if category not in DATA_SOURCE_CATEGORIES:
        category = "other"
    digest = _sha256_bytes(raw_data)
    source_id = f"user-{time.strftime('%Y%m%d%H%M%S')}-{digest[:10]}"
    upload_dir = _user_source_dir(root)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{source_id}-{original_name}"
    path = upload_dir / stored_name
    path.write_bytes(raw_data)
    relative_path = path.relative_to(root).as_posix()
    item = {
        "id": source_id,
        "name": original_name,
        "category": category,
        "description": fields.get("description", ""),
        "path": relative_path,
        "size": len(raw_data),
        "sha256": digest,
        "content_type": file_part.get("content_type", ""),
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    items = [entry for entry in _load_user_source_manifest(root) if entry.get("id") != source_id]
    items.append(item)
    _write_user_source_manifest(root, items)
    return item


def _delete_uploaded_data_source(root: Path, source_id: str) -> dict[str, object]:
    source_id = str(source_id or "").strip()
    if not source_id:
        raise ValueError("缺少数据源 ID。")
    upload_dir = _user_source_dir(root).resolve()
    items = _load_user_source_manifest(root)
    target = next((item for item in items if item.get("id") == source_id), None)
    if not target:
        raise ValueError("未找到可删除的数据源。")
    target_path = (root / str(target.get("path") or "")).resolve()
    if upload_dir not in target_path.parents:
        raise ValueError("拒绝删除非上传目录内的数据。")
    if target_path.exists():
        target_path.unlink()
    remaining = [item for item in items if item.get("id") != source_id]
    _write_user_source_manifest(root, remaining)
    return {"deleted": True, "id": source_id}


def _csv_response(rows: list[dict[str, object]], fieldnames: list[str]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _export_admission_records(db_path: Path, year: int) -> bytes:
    with connect(db_path) as connection:
        init_db(connection)
        rows = connection.execute(
            """
            SELECT year, source_id, school_code, school_name, major_code, major_name,
                   min_score, min_rank, plan_count, subjects, province, city,
                   school_level, school_type, tuition, tags
            FROM admission_records
            WHERE year = ?
            ORDER BY school_code, major_code, major_name
            """,
            (year,),
        ).fetchall()
    return _csv_response(
        [dict(row) for row in rows],
        [
            "year",
            "source_id",
            "school_code",
            "school_name",
            "major_code",
            "major_name",
            "min_score",
            "min_rank",
            "plan_count",
            "subjects",
            "province",
            "city",
            "school_level",
            "school_type",
            "tuition",
            "tags",
        ],
    )


def _export_score_rank_records(db_path: Path, year: int) -> bytes:
    with connect(db_path) as connection:
        init_db(connection)
        rows = connection.execute(
            """
            SELECT year, source_id, score, segment_count, cumulative_count, subject_group
            FROM score_rank_records
            WHERE year = ?
            ORDER BY score DESC
            """,
            (year,),
        ).fetchall()
    return _csv_response(
        [dict(row) for row in rows],
        ["year", "source_id", "score", "segment_count", "cumulative_count", "subject_group"],
    )


def _export_data_source(root: Path, db_path: Path, data_type: str, year: int | None = None) -> tuple[bytes, str, str]:
    if data_type == "admission":
        if year is None:
            raise ValueError("导出历史招录/计划必须指定年度。")
        return _export_admission_records(db_path, year), "text/csv; charset=utf-8", f"admission_records_{year}.csv"
    if data_type == "score_rank":
        if year is None:
            raise ValueError("导出一分一段表必须指定年度。")
        return _export_score_rank_records(db_path, year), "text/csv; charset=utf-8", f"score_rank_{year}.csv"
    config = MANAGED_FILE_DATASETS.get(data_type)
    if not config:
        raise ValueError("未知导出类型。")
    path = root / _managed_file_path(data_type, year)
    if not path.exists():
        raise ValueError("该数据源文件不存在。")
    suffix = path.suffix.lower()
    content_type = "application/json; charset=utf-8" if suffix == ".json" else "text/csv; charset=utf-8" if suffix == ".csv" else "application/octet-stream"
    return path.read_bytes(), content_type, path.name


def _record_column_defs(columns: list[str], readonly: set[str] | None = None) -> list[dict[str, object]]:
    readonly = readonly or set()
    return [
        {
            "key": column,
            "label": DATA_RECORD_LABELS.get(column, column),
            "editable": column not in readonly,
        }
        for column in columns
    ]


def _record_display_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            return "、".join(str(item) for item in value)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _parse_record_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in re.split(r"[,，、;；|/]+", text) if item.strip()]


def _coerce_record_value(value: object, original: object = "", integer: bool = False, list_field: bool = False) -> object:
    if list_field:
        return _parse_record_list(value)
    text = str(value or "").strip()
    if isinstance(original, bool):
        return text.lower() in {"1", "true", "yes", "y", "on", "是", "已找到"}
    if integer:
        return None if text == "" else int(float(text))
    if isinstance(original, int) and not isinstance(original, bool):
        return None if text == "" else int(float(text))
    if isinstance(original, float):
        return None if text == "" else float(text)
    if isinstance(original, (dict, list)):
        if text == "":
            return [] if isinstance(original, list) else {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("列表或对象字段必须填写有效 JSON。") from exc
    return text


def _paginate_rows(rows: list[dict[str, object]], page: int, page_size: int) -> tuple[list[dict[str, object]], int]:
    total = len(rows)
    page = max(1, min(page, max(1, (total + page_size - 1) // page_size)))
    start = (page - 1) * page_size
    return rows[start:start + page_size], page


def _row_matches_query(row: dict[str, object], query: str) -> bool:
    if not query:
        return True
    needle = query.lower()
    return any(needle in _record_display_value(value).lower() for value in row.values())


def _database_records_payload(
    db_path: Path,
    data_type: str,
    year: int | None,
    query: str,
    page: int,
    page_size: int,
) -> dict[str, object]:
    config = DATABASE_RECORD_DATASETS.get(data_type)
    if not config:
        raise ValueError("该数据库数据类型不可查看。")
    table = str(config["table"])
    columns = list(config["columns"])
    readonly = set(config.get("readonly", set()))
    where: list[str] = []
    params: list[object] = []
    if year is not None:
        where.append("year = ?")
        params.append(year)
    if query:
        search_columns = list(config.get("search", []))
        where.append("(" + " OR ".join(f"CAST({column} AS TEXT) LIKE ?" for column in search_columns) + ")")
        params.extend([f"%{query}%" for _ in search_columns])
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    with connect(db_path) as connection:
        init_db(connection)
        total = int(connection.execute(f"SELECT COUNT(*) FROM {table}{where_sql}", params).fetchone()[0])
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size
        rows = connection.execute(
            f"SELECT {', '.join(columns)} FROM {table}{where_sql} ORDER BY {config['order']} LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()
    return {
        "data_type": data_type,
        "year": year or "",
        "source_label": config["label"],
        "columns": _record_column_defs(columns, readonly),
        "rows": [
            {
                "key": str(row["id"]),
                "values": {column: _record_display_value(row[column]) for column in columns},
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _csv_records_payload(path: Path, data_type: str, query: str, page: int, page_size: int) -> dict[str, object]:
    if not path.exists():
        raise ValueError("该基础数据文件不存在。")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        all_rows = []
        for index, row in enumerate(reader):
            values = {column: _record_display_value(row.get(column, "")) for column in columns}
            if _row_matches_query(values, query):
                all_rows.append({"key": str(index), "values": values})
    page_rows, page = _paginate_rows(all_rows, page, page_size)
    return {
        "data_type": data_type,
        "year": "",
        "source_label": DATA_SOURCE_CATEGORIES.get(data_type, data_type),
        "columns": _record_column_defs(columns),
        "rows": page_rows,
        "total": len(all_rows),
        "page": page,
        "page_size": page_size,
    }


def _json_collection_rows(data_type: str, payload: dict[str, object]) -> tuple[list[str], set[str], set[str], list[dict[str, object]]]:
    config = JSON_RECORD_DATASETS.get(data_type)
    if not config:
        raise ValueError("该 JSON 数据类型不可查看。")
    collection = payload.get(str(config["collection"]))
    columns = list(config["columns"])
    readonly = set(config.get("readonly", set()))
    list_fields = set(config.get("list_fields", set()))
    key_label = str(config.get("key_label") or "")
    rows: list[dict[str, object]] = []
    if config["kind"] == "list":
        if not isinstance(collection, list):
            raise ValueError("JSON 主集合不是列表。")
        for index, item in enumerate(collection):
            source = item if isinstance(item, dict) else {"value": item}
            rows.append({"key": str(index), "values": {column: _record_display_value(source.get(column, "")) for column in columns}})
    else:
        if not isinstance(collection, dict):
            raise ValueError("JSON 主集合不是对象。")
        for key, item in collection.items():
            source = item if isinstance(item, dict) else {"value": item}
            values = {column: _record_display_value(source.get(column, "")) for column in columns}
            if key_label:
                values[key_label] = str(key)
            rows.append({"key": str(key), "values": values})
    return columns, readonly, list_fields, rows


def _json_records_payload(path: Path, data_type: str, query: str, page: int, page_size: int) -> dict[str, object]:
    if not path.exists():
        raise ValueError("该基础数据文件不存在。")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("JSON 顶层必须是对象。")
    columns, readonly, _list_fields, rows = _json_collection_rows(data_type, payload)
    filtered = [row for row in rows if _row_matches_query(row["values"], query)]
    page_rows, page = _paginate_rows(filtered, page, page_size)
    return {
        "data_type": data_type,
        "year": "",
        "source_label": DATA_SOURCE_CATEGORIES.get(data_type, data_type),
        "columns": _record_column_defs(columns, readonly),
        "rows": page_rows,
        "total": len(filtered),
        "page": page,
        "page_size": page_size,
    }


def _data_source_records_payload(
    root: Path,
    db_path: Path,
    data_type: str,
    year: int | None,
    query: str,
    page: int,
    page_size: int,
) -> dict[str, object]:
    page = max(1, page)
    page_size = max(10, min(page_size, 100))
    if data_type in DATABASE_RECORD_DATASETS:
        return _database_records_payload(db_path, data_type, year, query, page, page_size)
    config = MANAGED_FILE_DATASETS.get(data_type)
    if not config:
        raise ValueError("未知数据源类型。")
    path = root / _managed_file_path(data_type, year)
    if path.suffix.lower() == ".csv":
        return _csv_records_payload(path, data_type, query, page, page_size)
    if path.suffix.lower() == ".json":
        return _json_records_payload(path, data_type, query, page, page_size)
    raise ValueError("该文件类型暂不支持原始记录展示。")


def _update_database_record(db_path: Path, data_type: str, key: str, values: dict[str, object]) -> dict[str, object]:
    config = DATABASE_RECORD_DATASETS.get(data_type)
    if not config:
        raise ValueError("该数据库数据类型不可编辑。")
    table = str(config["table"])
    readonly = set(config.get("readonly", set()))
    columns = set(config["columns"]) - readonly
    integer_fields = set(config.get("integer", set()))
    updates: list[str] = []
    params: list[object] = []
    for column, value in values.items():
        if column not in columns:
            continue
        updates.append(f"{column} = ?")
        params.append(_coerce_record_value(value, integer=column in integer_fields))
    if not updates:
        raise ValueError("没有可保存的字段。")
    record_id = int(key)
    with connect(db_path) as connection:
        init_db(connection)
        params.append(record_id)
        cursor = connection.execute(f"UPDATE {table} SET {', '.join(updates)} WHERE id = ?", params)
        if data_type == "admission":
            connection.execute("UPDATE admission_records SET option_key = school_code || ':' || major_code WHERE id = ?", (record_id,))
        connection.commit()
    if not cursor.rowcount:
        raise ValueError("未找到要保存的记录。")
    return {"updated": True, "data_type": data_type, "key": key}


def _write_csv_rows(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    path.write_text("\ufeff" + output.getvalue(), encoding="utf-8")


def _update_csv_record(root: Path, path: Path, key: str, values: dict[str, object]) -> dict[str, object]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    row_index = int(key)
    if row_index < 0 or row_index >= len(rows):
        raise ValueError("未找到要保存的 CSV 记录。")
    changed = False
    for column, value in values.items():
        if column in columns:
            rows[row_index][column] = str(value or "")
            changed = True
    if not changed:
        raise ValueError("没有可保存的字段。")
    backup = _backup_file_if_exists(root, path)
    _write_csv_rows(path, columns, rows)
    _clear_data_source_caches()
    return {"updated": True, "key": key, "backup": backup}


def _update_json_record(root: Path, path: Path, data_type: str, key: str, values: dict[str, object]) -> dict[str, object]:
    config = JSON_RECORD_DATASETS.get(data_type)
    if not config:
        raise ValueError("该 JSON 数据类型不可编辑。")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("JSON 顶层必须是对象。")
    collection_name = str(config["collection"])
    collection = payload.get(collection_name)
    readonly = set(config.get("readonly", set()))
    columns = set(config["columns"]) - readonly
    list_fields = set(config.get("list_fields", set()))
    if config["kind"] == "list":
        if not isinstance(collection, list):
            raise ValueError("JSON 主集合不是列表。")
        row_index = int(key)
        if row_index < 0 or row_index >= len(collection):
            raise ValueError("未找到要保存的 JSON 记录。")
        target = collection[row_index]
        if not isinstance(target, dict):
            target = {"value": target}
            collection[row_index] = target
    else:
        if not isinstance(collection, dict) or key not in collection:
            raise ValueError("未找到要保存的 JSON 记录。")
        target = collection[key]
        if not isinstance(target, dict):
            target = {"value": target}
            collection[key] = target
    changed = False
    for column, value in values.items():
        if column not in columns:
            continue
        target[column] = _coerce_record_value(
            value,
            original=target.get(column, [] if column in list_fields else ""),
            list_field=column in list_fields,
        )
        changed = True
    if not changed:
        raise ValueError("没有可保存的字段。")
    backup = _backup_file_if_exists(root, path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _clear_data_source_caches()
    return {"updated": True, "data_type": data_type, "key": key, "backup": backup}


def _update_data_source_record(root: Path, db_path: Path, payload: dict[str, object]) -> dict[str, object]:
    data_type = str(payload.get("data_type") or "")
    key = str(payload.get("key") or "")
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    if not data_type or not key:
        raise ValueError("缺少数据类型或记录 ID。")
    if not isinstance(values, dict) or not values:
        raise ValueError("缺少要保存的字段。")
    if data_type in DATABASE_RECORD_DATASETS:
        return _update_database_record(db_path, data_type, key, values)
    year_value = payload.get("year")
    year = int(year_value) if year_value not in {None, ""} else None
    config = MANAGED_FILE_DATASETS.get(data_type)
    if not config:
        raise ValueError("未知数据源类型。")
    path = root / _managed_file_path(data_type, year)
    if not path.exists():
        raise ValueError("该基础数据文件不存在。")
    if path.suffix.lower() == ".csv":
        result = _update_csv_record(root, path, key, values)
    elif path.suffix.lower() == ".json":
        result = _update_json_record(root, path, data_type, key, values)
    else:
        raise ValueError("该文件类型暂不支持记录编辑。")
    return {"data_type": data_type, **result}


def _backup_path_for(root: Path, target: Path) -> Path:
    backup_dir = root / "data" / "backups" / "data_source_manager"
    backup_dir.mkdir(parents=True, exist_ok=True)
    relative = target.relative_to(root).as_posix().replace("/", "__").replace("\\", "__")
    return backup_dir / f"{time.strftime('%Y%m%d%H%M%S')}-{relative}"


def _backup_file_if_exists(root: Path, target: Path) -> str:
    if not target.exists():
        return ""
    backup = _backup_path_for(root, target)
    shutil.copy2(target, backup)
    return backup.relative_to(root).as_posix()


def _validate_managed_file(data_type: str, path: Path) -> None:
    config = MANAGED_FILE_DATASETS.get(data_type)
    if not config:
        raise ValueError("未知基础文件类型。")
    suffix = path.suffix.lower()
    if suffix not in config["extensions"]:
        allowed = "、".join(sorted(config["extensions"]))
        raise ValueError(f"{config['name']} 只支持 {allowed} 文件。")
    if suffix == ".json":
        json.loads(path.read_text(encoding="utf-8-sig"))
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
        if not header:
            raise ValueError("CSV 文件缺少表头。")


def _clear_data_source_caches() -> None:
    for func in (
        _load_discipline_quality_records,
        _load_postgraduate_rate_records,
        _load_science_top50k_reference_records,
        _discipline_quality_records_by_school,
        _discipline_quality_records_for_school,
        _find_postgraduate_rate_record,
        _official_2026_plan_supplement_records,
        _official_2026_plan_supplements_for_school,
        _science_top50k_reference_records_by_school,
        _science_top50k_reference_records_for_school,
    ):
        if hasattr(func, "cache_clear"):
            func.cache_clear()


def _import_data_source(root: Path, db_path: Path, content_type: str, body: bytes) -> dict[str, object]:
    fields, file_part = _parse_multipart_form(content_type, body)
    data_type = fields.get("data_type") or fields.get("category") or "other"
    mode = fields.get("mode") or "replace"
    year_value = fields.get("year") or ""
    year = int(year_value) if year_value else None
    saved = _save_uploaded_data_source(root, content_type, body)
    source_path = root / str(saved["path"])
    if data_type == "admission":
        records = load_admissions(source_path)
        years = sorted({record.year for record in records})
        if year is not None and years != [year]:
            raise ValueError(f"导入文件年份为 {years}，与选择年度 {year} 不一致。")
        if not years:
            raise ValueError("导入文件没有有效年份。")
        with connect(db_path) as connection:
            init_db(connection)
            if mode == "replace":
                for item_year in years:
                    connection.execute("DELETE FROM admission_records WHERE year = ?", (item_year,))
                connection.commit()
            batch_id, report = import_records(
                connection,
                records,
                str(source_path),
                batch_name=f"user-admission-{','.join(str(item) for item in years)}-{time.strftime('%Y%m%d%H%M%S')}",
            )
        return {
            "imported": True,
            "data_type": data_type,
            "years": years,
            "records": len(records),
            "batch_id": batch_id,
            "validation_errors": sum(1 for issue in report.issues if getattr(issue, "level", "") == "error"),
            "source": saved,
        }
    if data_type == "score_rank":
        records = load_score_ranks(source_path, year=year)
        years = sorted({record.year for record in records})
        if year is not None and years != [year]:
            raise ValueError(f"导入文件年份为 {years}，与选择年度 {year} 不一致。")
        if not years:
            raise ValueError("导入文件没有有效年份。")
        with connect(db_path) as connection:
            init_db(connection)
            if mode == "replace":
                for item_year in years:
                    connection.execute("DELETE FROM score_rank_records WHERE year = ?", (item_year,))
                connection.commit()
            batch_id = import_score_rank_records(
                connection,
                records,
                str(source_path),
                batch_name=f"user-score-rank-{','.join(str(item) for item in years)}-{time.strftime('%Y%m%d%H%M%S')}",
            )
        return {
            "imported": True,
            "data_type": data_type,
            "years": years,
            "records": len(records),
            "batch_id": batch_id,
            "source": saved,
        }
    config = MANAGED_FILE_DATASETS.get(data_type)
    if not config:
        raise ValueError("该数据类型暂不支持直接导入到系统。")
    _validate_managed_file(data_type, source_path)
    target = root / _managed_file_path(data_type, year)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = _backup_file_if_exists(root, target)
    shutil.copy2(source_path, target)
    _clear_data_source_caches()
    return {
        "imported": True,
        "data_type": data_type,
        "years": [year] if year else [],
        "records": "",
        "target": _managed_file_path(data_type, year),
        "backup": backup,
        "source": saved,
    }


def _delete_database_year(db_path: Path, data_type: str, year: int) -> int:
    table = "admission_records" if data_type == "admission" else "score_rank_records" if data_type == "score_rank" else ""
    if not table:
        raise ValueError("该数据类型不支持按年度删除。")
    with connect(db_path) as connection:
        init_db(connection)
        cursor = connection.execute(f"DELETE FROM {table} WHERE year = ?", (year,))
        count = int(cursor.rowcount or 0)
        connection.commit()
    return count


def _delete_managed_file(root: Path, data_type: str, year: int | None = None) -> dict[str, object]:
    config = MANAGED_FILE_DATASETS.get(data_type)
    if not config:
        raise ValueError("未知基础文件类型。")
    target = (root / _managed_file_path(data_type, year)).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents:
        raise ValueError("拒绝删除项目目录外的数据。")
    backup = _backup_file_if_exists(root, target)
    if target.exists():
        target.unlink()
    _clear_data_source_caches()
    return {"deleted": True, "data_type": data_type, "year": year or "", "backup": backup}


def _delete_data_source(root: Path, db_path: Path, payload: dict[str, object]) -> dict[str, object]:
    source_id = str(payload.get("id") or "")
    if source_id.startswith("user-"):
        return _delete_uploaded_data_source(root, source_id)
    data_type = str(payload.get("data_type") or "")
    if not data_type and source_id.startswith("db:"):
        parts = source_id.split(":")
        if len(parts) == 3:
            data_type = parts[1]
            payload["year"] = parts[2]
    if not data_type and source_id.startswith("file:"):
        data_type = source_id.split(":", 1)[1]
    if data_type in {"admission", "score_rank"}:
        year = int(payload.get("year") or 0)
        if not year:
            raise ValueError("删除历年数据必须指定年度。")
        count = _delete_database_year(db_path, data_type, year)
        return {"deleted": True, "data_type": data_type, "year": year, "records": count}
    if data_type in MANAGED_FILE_DATASETS:
        year = int(payload.get("year") or 0) or None
        return _delete_managed_file(root, data_type, year)
    raise ValueError("未找到可删除的数据源。")


def _str_arg(query: dict[str, list[str]], key: str, default: str = "") -> str:
    return query.get(key, [default])[0]


def _int_arg(query: dict[str, list[str]], key: str, default: int = 0, required: bool = False) -> int:
    value = query.get(key, [None])[0]
    if value in {None, ""}:
        if required:
            raise ValueError(f"Missing required parameter: {key}")
        return default
    return int(value)


def _bounded_int_arg(
    query: dict[str, list[str]],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
    required: bool = False,
) -> int:
    value = _int_arg(query, key, default=default, required=required)
    if value < minimum or value > maximum:
        raise ValueError(f"{key} 必须在 {minimum}-{maximum} 之间。")
    return value


def _optional_int_arg(query: dict[str, list[str]], key: str) -> int | None:
    value = query.get(key, [""])[0]
    if value in {"", None}:
        return None
    return int(value)


def _bounded_optional_int_arg(
    query: dict[str, list[str]],
    key: str,
    minimum: int,
    maximum: int,
) -> int | None:
    value = _optional_int_arg(query, key)
    if value is None:
        return None
    if value < minimum or value > maximum:
        raise ValueError(f"{key} 必须在 {minimum}-{maximum} 之间。")
    return value


def _bool_arg(query: dict[str, list[str]], key: str) -> bool:
    return query.get(key, ["0"])[0] in {"1", "true", "True", "on", "yes"}


def _list_arg(query: dict[str, list[str]], key: str) -> list[str]:
    value = query.get(key, [""])[0]
    return [item.strip() for item in value.replace("，", ",").replace("、", ",").split(",") if item.strip()]


def _custom_quotas_arg(query: dict[str, list[str]]) -> dict[str, int] | None:
    value = query.get("custom_quotas", [""])[0]
    if not value:
        return None
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("自定义方案数量格式不正确。") from exc
    if not isinstance(raw, dict):
        raise ValueError("自定义方案数量格式不正确。")
    quotas: dict[str, int] = {}
    for band in ("高冲", "冲", "稳中偏冲", "稳", "保", "强保"):
        try:
            count = int(raw.get(band, 0))
        except (TypeError, ValueError):
            count = 0
        quotas[band] = max(0, count)
    total = sum(quotas.values())
    if total > 150:
        raise ValueError("自定义方案数量不能超过 150。")
    return quotas if total > 0 else None


def _custom_risk_gaps_arg(query: dict[str, list[str]]) -> dict[str, int] | None:
    value = query.get("custom_risk_gaps", [""])[0]
    if not value:
        return None
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("自定义分差设定格式不正确。") from exc
    if not isinstance(raw, dict):
        raise ValueError("自定义分差设定格式不正确。")
    gaps: dict[str, int] = {}
    for key, default in (("challenge", 12), ("steady", 12), ("safe", 12)):
        try:
            value = int(raw.get(key, default))
        except (TypeError, ValueError):
            value = default
        value = max(0, value)
        if value > 100:
            raise ValueError("自定义分差不能超过 100 分。")
        gaps[key] = value
    return gaps


def _plan_2026_status(db_path: Path) -> dict[str, object]:
    data_dir = db_path.parent.parent
    candidates = list((data_dir / "raw" / "sdzk").glob("*2026*计划*")) if (data_dir / "raw" / "sdzk").exists() else []
    official_status = _load_official_2026_status(db_path)
    plan_item = ((official_status or {}).get("items") or {}).get("admission_plan") or {}
    checked_at = (official_status or {}).get("checked_at") or ""
    plan_title = str(plan_item.get("title") or "")
    supplement_found = bool(plan_item.get("found")) and "补充" in plan_title
    full_plan_candidates = [
        path
        for path in candidates
        if path.name not in {"sdzk_2026_admission_plan.html", "sdzk_2026_admission_plan.docx"}
    ]
    official_loaded = (bool(plan_item.get("found")) and not supplement_found) or any(
        path.suffix.lower() in {".xls", ".xlsx", ".csv", ".json", ".pdf", ".html"} for path in full_plan_candidates
    )
    if official_loaded:
        label = "已发现 2026 招生计划原始文件"
        method = "发现本地 2026 招生计划文件后，还要整理成每个学校专业都能核对的表。"
    elif supplement_found:
        label = "已发现 2026 分专业招生计划补充信息（非完整计划）"
        method = (
            "山东省教育招生考试院已发布本科分专业招生计划补充信息；系统已将命中项用于停招、计划数和收费提示，"
            "但完整 2026 分专业计划仍需以填报指南或志愿填报系统为准。"
        )
    elif checked_at:
        label = "本次官方扫描未发现 2026 分专业招生计划"
        method = f"已扫描山东招考院公开页，截至 {checked_at[:16]} 未发现可归档的 2026 分专业招生计划文件；暂用 2023-2025 往年计划数做临时参考。"
    else:
        label = "官方分专业招生计划待导入"
        method = "现在先用 2023-2025 往年计划数做临时参考，正式填报前必须换成今年官方计划。"
    return {
        "official_loaded": official_loaded,
        "official_supplement_found": supplement_found,
        "official_scan_found": bool(plan_item.get("found")),
        "checked_at": checked_at,
        "label": label,
        "method": method,
        "source": "正式填报必须以山东省教育招生考试院和院校 2026 招生计划为准。",
        "local_files": [str(path.relative_to(data_dir.parent)) for path in candidates[:12]],
    }


def _load_official_2026_status(db_path: Path) -> dict[str, object] | None:
    path = db_path.parent / "official_2026_status.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "checked_at": "",
            "authority": "山东省教育招生考试院",
            "scope": "2026 官方公开数据状态核验",
            "load_error": f"{path.name} 解析失败",
            "items": {},
        }


def _data_lineage_payload(
    batches: list[dict[str, object]],
    major_catalog: dict,
    plan_status: dict[str, object],
    official_2026_status: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "admission_batches": batches,
        "major_catalog": {
            "source": major_catalog.get("source", ""),
            "official_url": major_catalog.get("official_url", ""),
            "count": major_catalog.get("count", 0),
        },
        "plan_2026_status": plan_status,
        "official_2026_status": official_2026_status,
        "scope": "山东省普通类常规批第1次志愿；不覆盖提前批、强基、综招、艺术体育、春季高考等特殊类型。",
    }


def _backtest_summary(admissions) -> dict[str, object]:
    by_key: dict[str, list] = {}
    ambiguous_keys = ambiguous_stable_option_keys(admissions)
    for record in admissions:
        by_key.setdefault(option_group_key(record, ambiguous_keys), []).append(record)
    abs_errors: list[float] = []
    signed_errors: list[float] = []
    for records in by_key.values():
        by_year = {record.year: record for record in records if record.min_rank is not None}
        actual = by_year.get(2025)
        previous = [by_year.get(2023), by_year.get(2024)]
        previous = [record for record in previous if record is not None]
        if not actual or not previous:
            continue
        predicted = sum(record.min_rank for record in previous) / len(previous)
        error = actual.min_rank - predicted
        signed_errors.append(error)
        abs_errors.append(abs(error))
    abs_errors.sort()
    sample_count = len(abs_errors)
    if not sample_count:
        return {
            "sample_count": 0,
            "median_abs_error": None,
            "p75_abs_error": None,
            "within_3000_rate": None,
            "within_5000_rate": None,
            "grade": "待接入",
            "summary": "没有足够历史样本完成回测。",
            "method": "用前两年最低位次预测后一年的最低位次，并统计误差。",
        }
    within_3000 = sum(1 for value in abs_errors if value <= 3000) / sample_count * 100
    within_5000 = sum(1 for value in abs_errors if value <= 5000) / sample_count * 100
    p75 = abs_errors[min(sample_count - 1, int(sample_count * 0.75))]
    median_error = float(median(abs_errors))
    grade = "稳健" if within_5000 >= 70 else "可参考" if within_5000 >= 50 else "波动较大"
    return {
        "sample_count": sample_count,
        "median_abs_error": round(median_error),
        "p75_abs_error": round(p75),
        "within_3000_rate": round(within_3000),
        "within_5000_rate": round(within_5000),
        "mean_signed_error": round(sum(signed_errors) / sample_count),
        "grade": grade,
        "summary": f"历史回测显示，约 {round(within_5000)}% 的样本预测误差在 5000 位以内。",
        "method": "用 2023-2024 的数据去估 2025，再看估出来的名次和真实 2025 名次差多少。这个只说明系统稳不稳，不代表录取概率。",
    }


def _edge_case_warnings(rank: int, candidate: CandidateProfile, score_ranks) -> list[str]:
    warnings: list[str] = []
    max_rank = max((record.cumulative_count for record in score_ranks), default=None)
    if rank <= 100:
        warnings.append("极高位次边界：前100名样本极少，清北、强基、拔尖计划、院系偏好和专业冷热门会显著影响结果，必须人工单独复核。")
    elif rank <= 500:
        warnings.append("高位次边界：头部高校专业组波动较大，建议额外人工比较强基、综招、提前批和热门专业分流。")
    if max_rank and rank > max_rank:
        warnings.append(f"位次超过当前一分一段表最大累计人数 {max_rank}，系统只能给出低可靠参考。")
    warnings.append("适用范围提醒：当前系统主要覆盖山东普通类常规批，不覆盖艺术体育类、春季高考、提前批、强基计划、综合评价和专项计划。")
    return warnings


def _commercial_readiness_payload(
    plan_status: dict[str, object],
    backtest: dict[str, object],
    recommendations: list[dict],
    edge_warnings: list[str],
    major_catalog: dict,
) -> list[dict[str, str]]:
    single_year = sum(1 for item in recommendations if item.get("debug", {}).get("evidence_quality", {}).get("valid_years") == 1)
    charter_risk = sum(1 for item in recommendations if item.get("debug", {}).get("charter_risks"))
    identity_ready = sum(1 for item in recommendations if item.get("debug", {}).get("identity", {}).get("option_code"))
    official_plan_loaded = bool(plan_status.get("official_loaded"))
    return [
        {
            "title": "招生计划数",
            "status": "发现补充" if plan_status.get("official_supplement_found") and not official_plan_loaded else "已建核查位" if not official_plan_loaded else "发现文件",
            "level": "warn" if not official_plan_loaded else "ok",
            "detail": plan_status.get("label", "待核查"),
            "action": "导入完整官方分专业计划后，将估算值替换为官方计划数；已发布的官方补充信息会优先覆盖命中项。",
        },
        {
            "title": "招生章程风险",
            "status": f"命中 {charter_risk} 项",
            "level": "warn" if charter_risk else "ok",
            "detail": "按医学、语言、合作办学、公安航海、实验类等规则提示风险。",
            "action": "正式版应继续接入逐校章程原文和条款来源。",
        },
        {
            "title": "历史回测",
            "status": str(backtest.get("grade", "待接入")),
            "level": "ok" if backtest.get("grade") == "稳健" else "warn",
            "detail": backtest.get("summary", "等待回测。"),
            "action": "每次改推荐规则后，都要重新用历史数据测试一遍。",
        },
        {
            "title": "同名专业区分",
            "status": f"{identity_ready}/{len(recommendations)}",
            "level": "ok" if identity_ready == len(recommendations) else "warn",
            "detail": "展示招生代码、培养类型、校区、学费、选科等身份字段。",
            "action": "后续导入官方专业组/招生代码时继续增强。",
        },
        {
            "title": "专业知识库",
            "status": f"{major_catalog.get('count', 0)} 个专业",
            "level": "ok" if major_catalog.get("count", 0) else "warn",
            "detail": "使用 2026 本科专业目录和重点专业差异提醒。",
            "action": "继续补充培养方案、职业资格、转专业限制。",
        },
        {
            "title": "单年样本提示",
            "status": f"{single_year} 项",
            "level": "warn" if single_year else "ok",
            "detail": "单年样本仍正常排序，但用红色证据标签提示可靠度不足。",
            "action": "正式填报前应人工复核这类志愿。",
        },
        {
            "title": "边界拦截",
            "status": f"{len(edge_warnings)} 条",
            "level": "warn" if edge_warnings else "ok",
            "detail": "识别极高位次、超范围位次和特殊批次适用边界。",
            "action": "不在覆盖范围内的考生必须转人工咨询。",
        },
        {
            "title": "正式报告",
            "status": "已升级",
            "level": "ok",
            "detail": "报告包含封面、回测、成熟度、边界、证据链和风险清单。",
            "action": "可继续接入服务端固定版式 PDF 生成。",
        },
        {
            "title": "方案版本",
            "status": "已简化",
            "level": "ok",
            "detail": "当前页面保留方案生成、排序、预览和导出能力，不再提供本机方案版本入口。",
            "action": "如需长期留档，可通过导出报告或后续人工服务记录完成。",
        },
        {
            "title": "须知与免责",
            "status": "已明示",
            "level": "ok",
            "detail": "页面和报告中标明适用范围、免责声明、隐私和人工复核要求。",
            "action": "上线收款前仍需律师审查服务协议。",
        },
    ]


def _compliance_payload() -> dict[str, object]:
    return {
        "scope": "仅供山东普通类常规批志愿参考。",
        "disclaimer": "生成内容仅供参考，不承诺录取结果，不替代山东省教育招生考试院、院校招生章程、官方招生计划和人工复核。",
        "privacy": "系统只在用户本机运行，没有后台服务器；除非用户主动发送截图、报告或软件文件，否则开发方/销售方看不到用户输入和生成结果。",
        "refund_policy_note": "商业化上线前需配置服务条款、退款规则和人工咨询边界。",
    }


def _load_charter_registry(db_path: Path) -> dict:
    path = db_path.parent / "charter_registry_2026.json"
    if not path.exists():
        return {
            "updated_at": "",
            "central_source_url": "https://gaokao.chsi.com.cn/zsgs/zhangcheng/",
            "schools": {},
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "updated_at": "",
            "central_source_url": "https://gaokao.chsi.com.cn/zsgs/zhangcheng/",
            "schools": {},
            "load_error": f"{path.name} 解析失败",
        }


def _school_name_from_option(option_name: str) -> str:
    return str(option_name or "").split(" / ")[0].strip()


def _base_school_name(name: str) -> str:
    for left, right in (("(", ")"), ("（", "）")):
        if left in name and right in name:
            return name.split(left, 1)[0].strip()
    return name.strip()


def _charter_search_url(name: str) -> str:
    return f"https://gaokao.chsi.com.cn/zsgs/zhangcheng/listVerifedZszc.do?method=index&yxmc={quote(_base_school_name(name))}"


def _charter_registry_entry(school: str, registry: dict) -> tuple[str, dict | None]:
    schools = registry.get("schools") or {}
    lookup = registry.get("_school_lookup")
    if lookup is None:
        lookup = {}
        for key, entry in schools.items():
            lookup[key] = (key, entry)
            lookup[_base_school_name(key)] = (key, entry)
            for alias in entry.get("aliases") or []:
                alias_text = str(alias or "").strip()
                if alias_text:
                    lookup[alias_text] = (key, entry)
                    lookup[_base_school_name(alias_text)] = (key, entry)
        registry["_school_lookup"] = lookup
    if school in schools:
        return school, schools[school]
    base_school = _base_school_name(school)
    if base_school in schools:
        return base_school, schools[base_school]
    if school in lookup:
        return lookup[school]
    if base_school in lookup:
        return lookup[base_school]
    return school, None


def _rule_applies_to_option(rule: dict, option_name: str) -> bool:
    keywords = [str(item).strip() for item in rule.get("major_keywords") or [] if str(item).strip()]
    if not keywords:
        return True
    return any(keyword in option_name for keyword in keywords)


def _charter_2026_payload(payload: dict, registry: dict, compact: bool = False) -> dict[str, object]:
    school = _school_name_from_option(str(payload.get("option_name") or ""))
    option_name = str(payload.get("option_name") or "")
    matched_school, entry = _charter_registry_entry(school, registry)
    if not entry:
        return {
            "status": "pending",
            "school": school,
            "matched_school": "",
            "source_title": "阳光高考招生章程检索",
            "source_url": _charter_search_url(school),
            "summary": "这个学校的 2026 招生章程还没整理进系统，请打开官方页面人工核对。",
            "rules": [],
            "checked_at": "",
        }
    rules = []
    for rule in (entry.get("rules") or []):
        summary = str(rule.get("summary") or rule.get("evidence") or "").strip()
        if not summary or not _rule_applies_to_option(rule, option_name):
            continue
        rules.append({
            "category": str(rule.get("category") or "章程要求"),
            "summary": summary,
            "evidence": "" if compact else str(rule.get("evidence") or rule.get("summary") or "").strip(),
        })
        if compact and len(rules) >= 2:
            break
    status = str(entry.get("status") or "pending")
    if status == "verified" and not rules:
        summary = "已接入 2026 官方章程；未在政治面貌、身体条件、单科分数、地域/校区四类中抽到明确限制，仍需打开原文复核。"
    else:
        summary = str(entry.get("summary") or ("已接入 2026 官方章程，命中相关限制条款。" if status == "verified" else "该校 2026 官方章程仍需人工核验。"))
    return {
        "status": status,
        "school": school,
        "matched_school": matched_school,
        "source_title": entry.get("source_title") or "2026 招生章程",
        "source_url": entry.get("source_url") or entry.get("list_url") or _charter_search_url(school),
        "official_school_url": entry.get("official_school_url") or "",
        "official_school_title": entry.get("official_school_title") or "",
        "published_at": entry.get("published_at") or "",
        "checked_at": entry.get("checked_at") or "",
        "summary": summary,
        "rules": rules[:2] if compact else rules[:6],
    }


def _discipline_quality_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "curated" / "discipline_quality.csv"


def _postgraduate_rate_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "curated" / "postgraduate_recommend_rates.csv"


def _science_top50k_reference_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "curated" / "science_top50k_reference.csv"


@lru_cache(maxsize=1)
def _load_discipline_quality_records() -> tuple[dict[str, str], ...]:
    path = _discipline_quality_path()
    if not path.exists():
        return tuple()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return tuple(
            {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
            if any(str(value or "").strip() for value in row.values())
        )


@lru_cache(maxsize=1)
def _load_postgraduate_rate_records() -> tuple[dict[str, str], ...]:
    path = _postgraduate_rate_path()
    if not path.exists():
        return tuple()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return tuple(
            {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
            if any(str(value or "").strip() for value in row.values())
        )


@lru_cache(maxsize=1)
def _load_science_top50k_reference_records() -> tuple[dict[str, str], ...]:
    path = _science_top50k_reference_path()
    if not path.exists():
        return tuple()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return tuple(
            {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
            if any(str(value or "").strip() for value in row.values())
        )


def _discipline_quality_payload(payload: dict) -> dict[str, object]:
    option_name = str(payload.get("option_name") or "")
    if " / " in option_name:
        school_name, major_name = option_name.split(" / ", 1)
    else:
        school_name = str(payload.get("school_name") or "")
        major_name = option_name
    school_name = school_name.strip()
    major_name = major_name.strip()
    rate_payload = _postgraduate_rate_payload(school_name)
    records = _discipline_quality_records_for_school(school_name)
    best: dict[str, str] | None = None
    best_rank: tuple[int, int, int, int] | None = None
    for record in records:
        record_school = record.get("school_name", "")
        if record_school and record_school != school_name and record_school not in school_name and school_name not in record_school:
            continue
        keywords = [
            item.strip()
            for item in str(record.get("major_keywords") or record.get("major_keyword") or "").replace("，", ",").split(",")
            if item.strip()
        ]
        discipline = record.get("discipline", "")
        matched_keywords = [keyword for keyword in keywords if keyword and keyword in major_name]
        if not matched_keywords and discipline and discipline in major_name:
            matched_keywords = [discipline]
        if not matched_keywords:
            continue
        rank = (
            _assessment_round_rank(record.get("assessment_round", "")),
            _source_confidence_rank(record.get("source_type", ""), record.get("confidence", "")),
            max(len(item) for item in matched_keywords),
            _assessment_grade_rank(record.get("assessment_grade", "")),
        )
        if best_rank is None or rank > best_rank:
            best = record
            best_rank = rank
    if not best:
        return rate_payload
    assessment_round = _assessment_round_label(best.get("assessment_round", ""))
    assessment_grade = best.get("assessment_grade", "")
    assessment_label = f"{assessment_round} {assessment_grade}".strip()
    result = {
        "discipline": best.get("discipline", ""),
        "assessment_grade": assessment_grade,
        "assessment_round": assessment_round,
        "discipline_assessment": assessment_label or assessment_grade,
        "source_type": best.get("source_type", ""),
        "confidence": best.get("confidence", ""),
        "note": best.get("note", ""),
        "source": best.get("source", ""),
        "source_url": best.get("source_url", ""),
        "updated_at": best.get("updated_at", ""),
    }
    result.update(rate_payload)
    return {key: value for key, value in result.items() if value}


@lru_cache(maxsize=1)
def _discipline_quality_records_by_school() -> dict[str, tuple[dict[str, str], ...]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for record in _load_discipline_quality_records():
        school = record.get("school_name", "").strip()
        if school:
            grouped.setdefault(school, []).append(record)
    return {school: tuple(records) for school, records in grouped.items()}


@lru_cache(maxsize=4096)
def _discipline_quality_records_for_school(school_name: str) -> tuple[dict[str, str], ...]:
    school_name = str(school_name or "").strip()
    by_school = _discipline_quality_records_by_school()
    records: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    def add_many(items: Iterable[dict[str, str]] | None) -> None:
        for item in items or ():
            key = (
                item.get("school_name", ""),
                item.get("assessment_round", ""),
                item.get("discipline", ""),
                item.get("assessment_grade", ""),
                item.get("source_id", ""),
            )
            if key in seen:
                continue
            records.append(item)
            seen.add(key)

    add_many(by_school.get(school_name))
    base = _base_school_name(school_name)
    if base and base != school_name:
        add_many(by_school.get(base))
    add_many(
        record
        for record in _load_discipline_quality_records()
        for record_school in [record.get("school_name", "")]
        if record_school and (record_school in school_name or school_name in record_school)
    )
    return tuple(records)


def _postgraduate_rate_payload(school_name: str) -> dict[str, object]:
    record = _find_postgraduate_rate_record(school_name)
    if not record:
        return {}
    rate = record.get("postgraduate_recommend_rate", "")
    result = {
        "postgraduate_recommend_rate": rate,
        "baoyan_rate": rate,
        "postgraduate_recommend_rate_display": record.get("rate_display", ""),
        "postgraduate_recommend_rate_cohort": record.get("cohort", ""),
        "postgraduate_recommend_quota": record.get("recommend_quota", ""),
        "postgraduate_recommend_rate_rank": record.get("rank", ""),
        "postgraduate_recommend_rate_source": record.get("source", ""),
        "postgraduate_recommend_rate_source_url": record.get("source_url", ""),
        "postgraduate_recommend_rate_source_type": record.get("source_type", ""),
        "postgraduate_recommend_rate_confidence": record.get("confidence", ""),
        "postgraduate_recommend_rate_note": record.get("note", ""),
    }
    return {key: value for key, value in result.items() if value}


@lru_cache(maxsize=4096)
def _find_postgraduate_rate_record(school_name: str) -> dict[str, str] | None:
    target = _normalize_school_for_rate(school_name)
    if not target:
        return None
    best: dict[str, str] | None = None
    best_score = -1
    for record in _load_postgraduate_rate_records():
        names = [record.get("school_name", "")]
        names.extend(str(record.get("school_aliases", "")).split("|"))
        for name in names:
            candidate = _normalize_school_for_rate(name)
            if not candidate:
                continue
            score = -1
            if candidate == target:
                score = 100
            elif candidate in target or target in candidate:
                score = min(len(candidate), len(target))
            if score > best_score:
                best = record
                best_score = score
    return best if best_score >= 2 else None


def _normalize_school_for_rate(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace(" ", "")
    text = re.sub(r"\(校本部\)$", "", text)
    text = re.sub(r"\(主校区\)$", "", text)
    aliases = {
        "北京大学医学部": "北京大学(医学部)",
        "复旦大学上海医学院": "复旦大学(上海医学院)",
        "上海交通大学医学院": "上海交通大学(医学院)",
        "山东大学威海分校": "山东大学(威海)",
    }
    return aliases.get(text, text)


def _assessment_round_rank(value: str) -> int:
    text = str(value or "")
    if "第五" in text or "5" in text:
        return 5
    if "第四" in text or "4" in text:
        return 4
    return 0


def _assessment_round_label(value: str) -> str:
    text = str(value or "").strip()
    if "第五" in text or text == "5":
        return "第五轮"
    if "第四" in text or text == "4":
        return "第四轮"
    return text


def _source_confidence_rank(source_type: str, confidence: str) -> int:
    text = f"{source_type} {confidence}"
    if "official" in text and "not_official" not in text:
        return 3
    if "school" in text or "confirmed" in text:
        return 2
    if "network" in text:
        return 1
    return 0


def _assessment_grade_rank(value: str) -> int:
    order = {
        "A+": 9,
        "A": 8,
        "A-": 7,
        "B+": 6,
        "B": 5,
        "B-": 4,
        "C+": 3,
        "C": 2,
        "C-": 1,
    }
    return order.get(str(value or "").strip(), 0)


def _recommendation_payload(item, charter_registry: dict | None = None, compact: bool = False) -> dict:
    payload = asdict(item)
    debug = dict(payload.get("debug") or {})
    supplemental_plan = _supplemental_2026_plan_payload(payload)
    estimate = _estimate_2026_plan(payload.get("evidence") or [])
    if supplemental_plan:
        debug["plan_count_2026"] = supplemental_plan["plan_count_2026"]
        debug["plan_count_2026_status"] = supplemental_plan["plan_count_2026_status"]
        debug["plan_count_2026_source"] = supplemental_plan.get("source", "")
        debug["plan_count_2026_source_type"] = supplemental_plan.get("source_type", "")
        debug["plan_count_2026_note"] = supplemental_plan.get("note", "")
    official_supplement = _official_2026_plan_supplement_payload(payload)
    if official_supplement:
        debug["official_2026_supplement"] = official_supplement
        if official_supplement.get("school_code") and official_supplement.get("major_code"):
            debug["school_code"] = official_supplement["school_code"]
            debug["major_code"] = official_supplement["major_code"]
        if "plan_count_2026" in official_supplement:
            debug["plan_count_2026"] = official_supplement["plan_count_2026"]
            debug["plan_count_2026_status"] = official_supplement["plan_count_2026_status"]
            debug["plan_count_2026_source"] = official_supplement.get("source", "")
            debug["plan_count_2026_source_type"] = official_supplement.get("source_type", "")
            debug["plan_count_2026_note"] = official_supplement.get("note", "")
        if official_supplement.get("tuition_2026") is not None:
            debug["tuition"] = official_supplement["tuition_2026"]
        warning = official_supplement.get("warning")
        if warning:
            payload["warnings"] = tuple(list(payload.get("warnings") or []) + [str(warning)])
    debug["plan_count_2026_estimated"] = estimate
    if "plan_count_2026_status" not in debug:
        debug["plan_count_2026_status"] = "estimated" if estimate is not None else "missing"
    charter_risks, charter_level = _charter_risks(payload)
    debug["charter_risks"] = charter_risks
    debug["charter_level"] = charter_level
    debug["charter_2026"] = _charter_2026_payload(payload, charter_registry or {}, compact=compact)
    debug["evidence_quality"] = _evidence_quality(payload.get("evidence") or [])
    payload["debug"] = debug
    debug["identity"] = _option_identity(payload)
    debug["major_knowledge"] = _major_knowledge(payload)
    discipline_quality = _discipline_quality_payload(payload)
    if discipline_quality:
        debug["discipline_quality"] = discipline_quality
    if compact:
        payload["comparisons"] = []
        payload["falsification_tests"] = list(payload.get("falsification_tests") or [])[:2]
    else:
        debug["review_checklist"] = _review_checklist(payload)
    payload["debug"] = debug
    return payload


def _is_2026_stopped_option(payload: dict) -> bool:
    return (payload.get("debug") or {}).get("plan_count_2026_status") == "stopped"


def _evidence_quality(evidence: list[dict]) -> dict[str, object]:
    valid_years = [point.get("year") for point in evidence if point.get("min_rank") is not None]
    plan_years = [point.get("year") for point in evidence if point.get("plan_count") is not None]
    if len(valid_years) >= 3:
        level = "strong"
        label = "三年证据"
    elif len(valid_years) == 2:
        level = "medium"
        label = "两年证据"
    elif len(valid_years) == 1:
        level = "weak"
        label = "单年样本"
    else:
        level = "weak"
        label = "无有效位次"
    return {
        "level": level,
        "label": label,
        "valid_years": len(valid_years),
        "plan_years": len(plan_years),
        "years": valid_years,
    }


def _option_identity(payload: dict) -> dict[str, object]:
    debug = payload.get("debug") or {}
    major = str(payload.get("option_name") or "").split(" / ")[-1]
    campus = ""
    for marker in ("威海", "青岛", "深圳", "珠海", "苏州", "中外合作", "校企合作"):
        if marker in payload.get("option_name", "") or marker in major:
            campus = marker
            break
    return {
        "option_code": f"{debug.get('school_code')}:{debug.get('major_code')}" if debug.get("school_code") and debug.get("major_code") else payload.get("option_key"),
        "school_code": debug.get("school_code", ""),
        "major_code": debug.get("major_code", ""),
        "stable_option_key": payload.get("option_key"),
        "school_type": debug.get("school_type") or _school_type_from_name(payload.get("option_name", "")),
        "campus": campus,
        "tuition": debug.get("tuition"),
        "subjects": list(debug.get("subjects") or []),
        "latest_year": debug.get("latest_year"),
        "latest_plan_count": debug.get("latest_plan_count"),
    }


def _school_type_from_name(name: str) -> str:
    if "中外合作" in name or "高收费" in name:
        return "中外合作/高收费"
    if "校企合作" in name:
        return "校企合作"
    if "地方专项" in name:
        return "地方专项"
    return ""


def _major_knowledge(payload: dict) -> list[str]:
    name = str(payload.get("option_name") or "")
    notes: list[str] = []
    if "临床医学" in name:
        notes.append("临床医学通常面向执业医师培养，需重点核对学制、规培、体检和选科要求")
    if "基础医学" in name:
        notes.append("基础医学主要偏科研和医学基础研究，不能简单等同于临床医学")
    if "口腔医学" in name:
        notes.append("口腔医学专业属性独立，需核对学制、体检、色觉和实习要求")
    if "护理" in name:
        notes.append("护理学就业和培养路径与临床/口腔差异大，且常有体检限制")
    if "信息管理与信息系统" in name:
        notes.append("信息管理与信息系统通常偏管理学/信息系统交叉，不等同于纯计算机开发")
    if "计算机" in name or "软件工程" in name:
        notes.append("计算机/软件方向需核对是否为大类招生、分流规则和校区")
    if "人工智能" in name:
        notes.append("人工智能需核对培养方案中数学、计算机和自动化课程比例")
    if "网络空间安全" in name or "信息安全" in name:
        notes.append("网络安全方向需核对专业归属、实验条件和是否大类分流")
    if "中外合作" in name or "高收费" in name:
        notes.append("中外合作/高收费项目需核对学费、外方学位、出国要求和转专业限制")
    if "工科试验班" in name or "理科试验班" in name:
        notes.append("试验班/大类招生必须核对分流规则，不能只按大类名称判断最终专业")
    return notes[:3]


def _review_checklist(payload: dict) -> list[str]:
    checks = [
        "核对 2026 官方分专业计划数",
        "核对院校招生章程",
        "核对选科、体检、单科、语种、校区和学费",
    ]
    name = str(payload.get("option_name") or "")
    if "医学" in name or "护理" in name or "药学" in name:
        checks.append("医学健康类需额外核对色觉、视力、职业资格和实习要求")
    if "中外合作" in name or "高收费" in name:
        checks.append("合作办学需额外核对培养地点、外方学位和转专业限制")
    if "试验班" in name:
        checks.append("大类/试验班需额外核对分流比例和可选专业范围")
    return checks


def _estimate_2026_plan(evidence: list[dict]) -> int | None:
    counts = [point.get("plan_count") for point in evidence if point.get("plan_count") is not None]
    if not counts:
        return None
    if len(counts) == 1:
        return int(counts[-1])
    recent = counts[-2:]
    return max(1, round(sum(recent) / len(recent)))


def _supplemental_2026_plan_payload(payload: dict) -> dict[str, object]:
    option_name = str(payload.get("option_name") or "")
    if " / " in option_name:
        school_name, major_name = option_name.split(" / ", 1)
    else:
        school_name = str(payload.get("school_name") or "")
        major_name = option_name
    school_name = school_name.strip()
    major_name = major_name.strip()
    if not school_name or not major_name:
        return {}
    records = _science_top50k_reference_records_for_school(school_name)
    best: dict[str, str] | None = None
    best_score = -1
    for record in records:
        aliases = [record.get("major_name", "")]
        aliases.extend(str(record.get("major_aliases", "")).split("|"))
        score = max((_major_alias_match_score(alias, major_name) for alias in aliases), default=-1)
        if score > best_score:
            best = record
            best_score = score
    if not best or best_score < 2:
        return {}
    try:
        plan_count = int(float(best.get("plan_count_2026", "")))
    except ValueError:
        return {}
    return {
        "plan_count_2026": plan_count,
        "plan_count_2026_status": "excel_reference",
        "source": best.get("source", ""),
        "source_type": best.get("source_type", ""),
        "note": best.get("note", ""),
        "simulated_rank": best.get("simulated_rank", ""),
    }


def _official_2026_plan_supplement_payload(payload: dict) -> dict[str, object]:
    school_code, major_code = _option_codes(payload.get("option_key"))
    debug = payload.get("debug") or {}
    school_code = str(debug.get("school_code") or school_code).strip().upper()
    major_code = str(debug.get("major_code") or major_code).strip().upper()
    option_name = str(payload.get("option_name") or "")
    if " / " in option_name:
        school_name, major_name = option_name.split(" / ", 1)
    else:
        school_name = str(payload.get("school_name") or "")
        major_name = option_name
    school_name = school_name.strip()
    major_name = major_name.strip()
    if not school_code and not school_name:
        return {}
    records = _official_2026_plan_supplements_for_school(school_code, school_name)
    if not records:
        return {}
    normalized_major = _normalize_exact_major_name(major_name)
    exact_code_matches = [
        record for record in records if major_code and record.get("major_code", "").upper() == major_code.upper()
    ]
    exact_name_matches = [
        record
        for record in records
        if normalized_major and _normalize_exact_major_name(record.get("major_name", "")) == normalized_major
    ]
    match = exact_code_matches[0] if exact_code_matches else exact_name_matches[0] if exact_name_matches else None
    if not match:
        return {}
    action = match.get("action", "")
    note = match.get("note", "")
    result: dict[str, object] = {
        "batch": match.get("batch", ""),
        "school_code": match.get("school_code", ""),
        "school_name": match.get("school_name", ""),
        "major_code": match.get("major_code", ""),
        "major_name": match.get("major_name", ""),
        "action": action,
        "note": note,
        "source": match.get("source", ""),
        "source_url": match.get("source_url", ""),
        "source_type": match.get("source_type", ""),
        "confidence": match.get("confidence", ""),
        "published_at": match.get("published_at", ""),
    }
    if action == "stopped":
        result.update(
            {
                "plan_count_2026": 0,
                "plan_count_2026_status": "stopped",
                "warning": f"2026 官方补充信息：{note or '该专业停止招生'}",
            }
        )
    elif action == "plan_adjusted":
        plan_count = _parse_int(match.get("plan_count_2026"))
        if plan_count is not None:
            result.update(
                {
                    "plan_count_2026": plan_count,
                    "plan_count_2026_status": "official_supplement",
                    "warning": f"2026 官方补充信息：{note or f'计划数调整为 {plan_count}'}",
                }
            )
    elif action == "tuition_adjusted":
        tuition = _parse_int(match.get("tuition_2026"))
        if tuition is not None:
            result["tuition_2026"] = tuition
        result["warning"] = f"2026 官方补充信息：{note or '收费标准调整'}"
    elif note:
        result["warning"] = f"2026 官方补充信息：{note}"
    return result


def _option_codes(option_key: object) -> tuple[str, str]:
    parts = str(option_key or "").split(":", 1)
    if len(parts) != 2:
        return "", ""
    return parts[0].strip().upper(), parts[1].strip().upper()


def _normalize_exact_major_name(value: str) -> str:
    return (
        str(value or "")
        .replace("（", "(")
        .replace("）", ")")
        .replace(" ", "")
        .strip()
    )


def _parse_int(value: object) -> int | None:
    try:
        text = str(value or "").strip()
        if not text:
            return None
        return int(float(text))
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _official_2026_plan_supplement_records() -> tuple[dict[str, str], ...]:
    path = Path(__file__).resolve().parents[1] / "data" / "curated" / "official_2026_plan_supplements.csv"
    if not path.exists():
        return tuple()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


@lru_cache(maxsize=512)
def _official_2026_plan_supplements_for_school(school_code: str, school_name: str) -> tuple[dict[str, str], ...]:
    code = str(school_code or "").strip().upper()
    name = _base_school_name(str(school_name or "").strip())
    matches = []
    for record in _official_2026_plan_supplement_records():
        record_code = record.get("school_code", "").strip().upper()
        record_name = _base_school_name(record.get("school_name", "").strip())
        if (code and record_code == code) or (name and record_name == name):
            matches.append(record)
    return tuple(matches)


@lru_cache(maxsize=1)
def _science_top50k_reference_records_by_school() -> dict[str, tuple[dict[str, str], ...]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for record in _load_science_top50k_reference_records():
        school = record.get("school_name", "").strip()
        if school:
            grouped.setdefault(school, []).append(record)
    return {school: tuple(records) for school, records in grouped.items()}


@lru_cache(maxsize=4096)
def _science_top50k_reference_records_for_school(school_name: str) -> tuple[dict[str, str], ...]:
    school_name = str(school_name or "").strip()
    by_school = _science_top50k_reference_records_by_school()
    exact = by_school.get(school_name)
    if exact:
        return exact
    base = _base_school_name(school_name)
    exact_base = by_school.get(base)
    if exact_base:
        return exact_base
    return tuple(
        record
        for record in _load_science_top50k_reference_records()
        for record_school in [record.get("school_name", "")]
        if record_school and (record_school in school_name or school_name in record_school)
    )


def _major_alias_match_score(alias: str, major_name: str) -> int:
    alias = str(alias or "").strip()
    major_name = str(major_name or "").strip()
    if not alias or not major_name:
        return -1
    if alias == major_name:
        return len(alias) + 100
    if alias in major_name or major_name in alias:
        return min(len(alias), len(major_name))
    alias_base = _base_major_name(alias)
    major_base = _base_major_name(major_name)
    if alias_base and major_base and (alias_base == major_base or alias_base in major_base or major_base in alias_base):
        return min(len(alias_base), len(major_base))
    return -1


def _base_major_name(value: str) -> str:
    return re.sub(r"[（(].*?[）)]", "", str(value or "").strip()).strip()


def _charter_risks(payload: dict) -> tuple[list[str], str]:
    name = str(payload.get("option_name") or "")
    risks: list[str] = []
    high_keywords = ("公安", "警察", "飞行", "航海", "轮机")
    medical_keywords = ("临床医学", "口腔医学", "基础医学", "医学影像", "医学检验", "药学", "中医学", "护理")
    lab_keywords = ("化学", "生物", "材料", "环境", "食品", "制药")
    language_keywords = ("英语", "外国语", "翻译", "商务英语", "日语", "朝鲜语", "俄语", "德语", "法语")
    if any(keyword in name for keyword in medical_keywords):
        risks.append("医学相关专业：重点核对色盲色弱、视力、体检和职业资格限制")
    if any(keyword in name for keyword in lab_keywords):
        risks.append("实验类专业：重点核对色觉、嗅觉和体检要求")
    if any(keyword in name for keyword in language_keywords):
        risks.append("语言类专业：重点核对语种限制和外语单科成绩要求")
    if "中外合作" in name or "高收费" in name:
        risks.append("中外合作/高收费：重点核对学费、培养地点、学位授予和转专业限制")
    if "师范" in name or "教育" in name:
        risks.append("师范/教育方向：核对教师资格、体检要求和就业去向")
    if any(keyword in name for keyword in high_keywords):
        risks.append("特殊培养方向：重点核对政审、体检、体能、身高或视力等硬性条件")
    if "校企合作" in name:
        risks.append("校企合作：核对收费、培养企业、实习安排和转专业限制")
    level = "high" if any(keyword in name for keyword in high_keywords) or "护理" in name else "medium" if risks else "low"
    return risks[:4], level


def _strategy_compare_payload(strategy: str, plan) -> dict:
    groups = _risk_group_counts(plan.risk_counts)
    total = len(plan.recommendations)
    charter_risk_count = 0
    for item in plan.recommendations:
        payload = _recommendation_payload(item)
        if payload.get("debug", {}).get("charter_risks"):
            charter_risk_count += 1
    stable_ratio = round((groups["steady"] + groups["safe"]) / total * 100) if total else 0
    return {
        "strategy": strategy,
        "total": total,
        "quotas": dict(plan.quotas),
        "challenge_count": groups["challenge"],
        "steady_count": groups["steady"],
        "safe_count": groups["safe"],
        "unknown_count": groups["unknown"],
        "stable_ratio": stable_ratio,
        "charter_risk_count": charter_risk_count,
        "warnings": list(plan.warnings),
        "top_recommendations": [
            {
                "option_name": item.option_name,
                "risk_band": item.risk_band,
                "weighted_reference_rank": item.weighted_reference_rank,
            }
            for item in plan.recommendations[:6]
        ],
    }


def _risk_group_counts(counts: dict[str, int]) -> dict[str, int]:
    return {
        "challenge": counts.get("高冲", 0) + counts.get("冲", 0) + counts.get("稳中偏冲", 0),
        "steady": counts.get("稳", 0),
        "safe": counts.get("保", 0) + counts.get("强保", 0),
        "unknown": counts.get("证据不足", 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local Shandong Gaokao decision app.")
    parser.add_argument("--db", default="data/processed/official.sqlite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), create_handler(Path(args.db)))
    print(f"Serving app on http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
