# fi-65F Scanner Camera CLI v0.4

Fujitsu/Ricoh fi-65Fを、通常の原稿スキャナとしてだけでなく、外部レンズで結像した像を取得するscanner camera実験に使用するためのWindows向けCLIです。

現在は、同じ設定・保存契約を持つ2つのバックエンドを並行して保持します。

- `scanner_capture.py`: WIA診断 + WIA制御 + WIA画像取得
- `twain_capture.py`: TWAIN Capability診断 + TWAIN制御 + TWAIN画像取得

共通仕様：

- CLIまたは`config.ini`で設定
- CLI指定を`config.ini`より優先
- Driver / Data Sourceが公開する設定能力を診断
- 診断結果をJSON/TXTへ保存
- 画像を`./jpeg/DSC_0001.jpeg`形式で連番保存
- 既存画像を上書きしない排他的な採番
- strict / non-strictによる未対応設定の扱い切替
- Windows専用。Linux/macOSは対象外

## 1. 動作環境

### 1.1 最終運用ターゲット

最終的な組み込み運用環境は以下を正本ターゲットとします。

- **Windows 8 32-bit (x86)**
- **Python 3.8.x 32-bit**
- 推奨: **Python 3.8.10 x86**
- fi-65F用32-bit WIA/TWAINドライバー
- TWAIN使用時は32-bit TWAIN DSM + 32-bit TWAIN Data Source

Windows 8.1ではなくWindows 8を対象にするため、Python 3.9以降ではなくPython 3.8系を互換性基準にします。

32-bit Pythonであることは次で確認します。

```bat
py -3.8-32 -c "import platform, struct; print(platform.python_version(), struct.calcsize('P') * 8)"
```

想定出力例：

```text
3.8.10 32
```

### 1.2 開発・回帰試験環境

開発機では新しいWindows/Pythonも使用できます。

現在のCIマトリクス：

- Python 3.8 / x86 — 最終運用環境のPython/bitness互換性確認
- Python 3.11 / x64 — 現行開発環境確認
- Python 3.12 / x64 — 現行開発環境確認

GitHub Actionsのrunner自体はWindows 8ではありません。そのためPython 3.8 x86 CIが保証するのは、**32-bit Pythonでコード・依存パッケージ・テストが成立すること**までです。

以下は実機で確認します。

- Windows 8 32-bit上での起動
- fi-65F WIA認識
- fi-65F TWAIN Data Source認識
- 実スキャン
- PaperStream固有Capability
- LED/露出関連Capability

### 1.3 Python依存関係

最終ターゲットでは次を使用します。

```bat
py -3.8-32 -m pip install -r requirements.txt
```

`requirements.txt`はPython 3.8向けに互換バージョンを条件分岐しています。

- `pywin32==308` — Python 3.8 x86用
- `Pillow>=10.0,<11.0` — Python 3.8用
- `pytwain>=2.3.0,<3.0`

Python 3.9以降では新しいpywin32/Pillowを使用できます。

古いPython環境では、`pip`自体を無条件に最新版へ更新しないでください。Python 3.8をサポートするpipを維持した状態で依存関係を導入します。

## 2. 32-bit / 64-bitの考え方

### 2.1 WIA

WIA版は`pywin32`からWindows WIA COMインターフェースを使用します。

`scanner_capture.py`は32-bit / 64-bit Windowsの両方を許容します。最終ターゲットではPython 3.8 x86 + 32-bit環境で使用します。

確認：

```bat
py -3.8-32 scanner_capture.py --list-devices
```

### 2.2 TWAIN

TWAINではbitnessの一致が重要です。

```text
Python process
      │
      ├── TWAIN DSM
      │
      └── TWAIN Data Source (scanner driver)
```

この3者を同じbitnessに揃えます。

最終ターゲット：

```text
Python 3.8 x86        32-bit
TWAIN DSM             32-bit
fi-65F Data Source    32-bit
```

開発機で64-bit Pythonを使う場合はDSM/Data Sourceも64-bitを使います。

`twain_capture.py`は実行中Pythonのbitnessを診断結果へ記録し、Sourceが見つからない場合も32/64-bitを含めてエラー表示します。

## 3. ファイル構成とコードの責務

```text
scanner_camera/
├─ scanner_capture.py          WIA診断・WIA制御・WIA画像取得
├─ twain_capture.py            TWAIN診断・Capability制御・TWAIN画像取得
├─ config.ini                  共通設定 + TWAIN固有設定
├─ requirements.txt            実行時依存パッケージ
├─ requirements-dev.txt        pytest等の開発依存パッケージ
├─ README.md                   動作環境・利用方法・コード構成
├─ TESTING.md                  自動試験と実機試験の責務
├─ tests/                      実機不要の単体テスト
├─ jpeg/                       DSC_####.jpeg出力先
└─ diagnostics/                WIA/TWAIN診断結果
```

### 3.1 `scanner_capture.py`

WIA経路を担当します。

主な処理：

1. WIA Scanner列挙
2. 名前の部分一致によるfi-65F選択
3. WIA Property列挙
4. Propertyの範囲・リスト・read-only状態確認
5. no-change write/read-back probe
6. DPI / mode / brightness / contrast / scan region設定
7. WIA転送
8. BMPからJPEGへ変換
9. `DSC_####.jpeg`採番・保存

WIA診断ではDriverが公開する全Propertyを記録します。WIAで公開されない設定をコード側で推測して操作することはしません。

### 3.2 `twain_capture.py`

TWAIN経路を担当します。

主な処理：

1. 実行中Pythonと同じbitnessのTWAIN Source Managerを開く
2. TWAIN Data Sourceを列挙
3. fi-65F Sourceを選択
4. `CAP_SUPPORTEDCAPS`から公開Capability IDを取得
5. scanner cameraで重要なCapabilityを追加照会
6. `GET` / `GETCURRENT` / `GETDEFAULT` / `MSG_QUERYSUPPORT`を診断
7. 必要なCapabilityだけno-change SET/read-back probe
8. Pixel Type / DPI / brightness等を設定
9. `DAT_IMAGELAYOUT`で読み取り範囲を設定
10. native transferで1画像を取得
11. BMPを中間形式としてJPEGへ変換
12. WIA版と共通の`DSC_####.jpeg`契約で保存

TWAINではData SourceごとにCapabilityの実装状況、値型、範囲が異なるため、有効値をコードへ決め打ちしません。実機の診断結果を正本として設定します。

### 3.3 共通採番

TWAIN版はWIA版の以下を再利用します。

- `read_config()`
- `config_value()`
- `reserve_output_path()`
- `remove_empty_reservation()`

出力：

```text
./jpeg/DSC_0001.jpeg
./jpeg/DSC_0002.jpeg
./jpeg/DSC_0003.jpeg
```

採番時は空ファイルを排他的に作成して番号を予約します。取り込み失敗時は空の予約ファイルだけを削除します。

## 4. WIA診断と取り込み

### 4.1 デバイス確認

最終ターゲット：

```bat
py -3.8-32 scanner_capture.py --list-devices
```

通常のPython launcher既定環境を使う場合：

```bat
py scanner_capture.py --list-devices
```

### 4.2 WIA診断

```bat
py -3.8-32 scanner_capture.py --device fi-65F --diagnose
```

出力：

```text
./diagnostics/wia_diagnostic_YYYYMMDD_HHMMSS.json
./diagnostics/wia_diagnostic_YYYYMMDD_HHMMSS.txt
```

診断では、対象設定ごとに公開状態、read-only状態、設定可能範囲、no-change write/read-back結果を記録します。

64-bit開発機での実機確認では以下を確認済みです。

- X/Y解像度: 75～600 dpi
- brightness: -128～127
- contrast: -128～127
- threshold: 1～255
- 24 bit RGB出力

この結果は64-bit WIA環境の実測です。32-bit Windows 8環境では改めて診断結果を取得します。

### 4.3 WIA取り込み

```bat
py -3.8-32 scanner_capture.py ^
  --device fi-65F ^
  --dpi 600 ^
  --mode color ^
  --brightness -128 ^
  --contrast 0
```

## 5. TWAIN診断と取り込み

### 5.1 Source確認

```bat
py -3.8-32 twain_capture.py --list-devices
```

fi-65Fが列挙されない場合、最初に以下を確認します。

- Pythonが32-bitか
- TWAIN DSMが32-bitか
- fi-65F Data Sourceが32-bitか

### 5.2 初回診断

初回はSETを行わない診断から開始します。

```bat
py -3.8-32 twain_capture.py --device fi-65F --diagnose --no-probe-writes
```

出力：

```text
./diagnostics/twain_diagnostic_YYYYMMDD_HHMMSS.json
./diagnostics/twain_diagnostic_YYYYMMDD_HHMMSS.txt
```

Sourceが安定して応答した後、no-change write/read-back probeを行います。

```bat
py -3.8-32 twain_capture.py --device fi-65F --diagnose
```

### 5.3 scanner cameraで重点確認するCapability

基本画像設定：

- `ICAP_PIXELTYPE`
- `ICAP_XRESOLUTION` / `ICAP_YRESOLUTION`
- `ICAP_BITDEPTH`
- `ICAP_BRIGHTNESS`
- `ICAP_CONTRAST`
- `ICAP_THRESHOLD`
- `ICAP_UNITS`
- `ICAP_XFERMECH`

露出・光源関連：

- `ICAP_AUTOBRIGHT`
- `ICAP_EXPOSURETIME`
- `ICAP_GAMMA`
- `ICAP_HIGHLIGHT`
- `ICAP_SHADOW`
- `ICAP_LAMPSTATE`
- `ICAP_LIGHTSOURCE`
- `ICAP_LIGHTPATH`
- `ICAP_PHYSICALWIDTH`
- `ICAP_PHYSICALHEIGHT`
- `ICAP_XNATIVERESOLUTION`
- `ICAP_YNATIVERESOLUTION`
- `DAT_IMAGELAYOUT`

TWAIN標準にCapabilityが存在することと、fi-65F/PaperStream Data Sourceが実装していることは別です。実機診断で`NOT_EXPOSED_BY_TWAIN`なら、その経路では使用できません。

### 5.4 診断ステータス

代表例：

- `NOT_EXPOSED_BY_TWAIN`: GET/CURRENT/DEFAULTから取得できない
- `EXPOSED_READABLE`: 読み出せるがSET probe未実施
- `EXPOSED_AND_SETTABLE`: no-change SET + read-back成功
- `EXPOSED_BUT_WRITE_REJECTED`: SET拒否
- `EXPOSED_SUPPORT_UNCERTAIN`: 一部問い合わせのみ成功

`--no-probe-writes`では書き込み確認を行いません。

通常の`--diagnose`でも全Capabilityへ無差別にSETせず、scanner_cameraで意味がある対象だけを現在値でprobeします。

### 5.5 基本取り込み

```bat
py -3.8-32 twain_capture.py ^
  --device fi-65F ^
  --dpi 600 ^
  --mode color ^
  --brightness -128 ^
  --contrast 0
```

### 5.6 TWAIN固有設定

診断で公開・SET可能と確認された値だけ指定します。

```bat
py -3.8-32 twain_capture.py ^
  --device fi-65F ^
  --dpi 600 ^
  --mode color ^
  --autobright off ^
  --exposure-time 1.0 ^
  --gamma 1.0 ^
  --lamp-state off
```

対応CLI：

- `--autobright on|off`
- `--exposure-time <value>`
- `--gamma <value>`
- `--lamp-state on|off`
- `--light-source <raw-value>`
- `--bit-depth <value>`

`ICAP_EXPOSURETIME`などの単位・有効範囲はData Source依存です。

## 6. 読み取り範囲

WIA/TWAINともCLIではピクセル単位で指定します。

```bat
--xpos 0 --ypos 0 --width 2480 --height 3496
```

- WIA: WIA Propertyへピクセル値を設定
- TWAIN: 指定DPIからインチへ換算し`DAT_IMAGELAYOUT`へ設定

例: 600 dpiで`width=600`ならTWAINへ1.0 inch幅として設定します。

## 7. `config.ini`

WIA/TWAINで共通利用します。

```ini
[scanner]
device = fi-65F
show_ui = false
strict_settings = true

[scan]
dpi = 600
mode = color
brightness = 0
contrast = 0

[region]
xpos =
ypos =
width =
height =

[twain]
dsm_name =
autobright =
exposure_time =
gamma =
lamp_state =
light_source =
bit_depth =

[output]
directory = ./jpeg
jpeg_quality = 95

[diagnostics]
directory = ./diagnostics
probe_writes = true
```

空欄は現在値/Driver既定値を維持します。

## 8. strict / non-strict

既定は`strict_settings = true`です。

TWAIN SourceがSETを受理しても、read-back値が要求値と異なる場合、strictではエラーにします。DPIが勝手に丸められた状態で画像領域換算やJPEGメタデータだけ要求値を使うことを防ぎます。

警告だけで継続する場合：

```bat
py -3.8-32 twain_capture.py --non-strict
```

## 9. 露出・LED制御の位置づけ

WIAで公開された`brightness`はfi-65F実機で画像変化を確認済みですが、物理的なCIS積分時間や露光時間そのものとは断定できません。

TWAINでは以下を追加診断します。

- `ICAP_AUTOBRIGHT`
- `ICAP_EXPOSURETIME`
- `ICAP_GAMMA`
- `ICAP_LAMPSTATE`
- `ICAP_LIGHTSOURCE`
- `ICAP_LIGHTPATH`

これらが32-bit PaperStream Data Sourceでも公開されるかは、Windows 8実機の診断結果で判断します。

`ICAP_LAMPSTATE`等が公開されない、またはSET拒否なら、内蔵LED停止はハード側改造の課題として扱います。

## 10. テスト

開発環境：

```bat
python -m pip install -r requirements-dev.txt
python -m pytest --cov=scanner_capture --cov=twain_capture --cov-report=term-missing
```

最終ターゲット相当のローカル試験：

```bat
py -3.8-32 -m pip install -r requirements-dev.txt
py -3.8-32 -m pytest
```

CIはPython 3.8 x86 / 3.11 x64 / 3.12 x64を実行します。

詳細は`TESTING.md`を参照してください。

## 11. 既知の検証境界

自動テストだけでは保証できない項目：

- Windows 8カーネル上でのpywin32/Pillow/pytwain実動作
- fi-65F 32-bit WIA Driver
- fi-65F 32-bit TWAIN Data Source
- TWAIN DSMとData Sourceの実際の組み合わせ
- PaperStream固有Capability
- 実native transfer
- LED制御
- 露光時間・積分時間
- 実画像のS/N・色・ダイナミックレンジ

これらはWindows 8 32-bit実機で検証します。
