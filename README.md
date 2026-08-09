# fi-65F Scanner Camera CLI v0.5 RC

Fujitsu/Ricoh fi-65Fを、通常の原稿スキャナとしてだけでなく、外部レンズで結像した像を取得するscanner camera実験に使用するためのWindows向けCLIです。

現在は2つのバックエンドを並行して保持します。

- `scanner_capture.py`: WIA診断 + WIA制御 + WIA画像取得
- `twain_capture.py`: TWAIN Capability診断 + TWAIN制御 + TWAIN画像取得

共通仕様：

- CLIまたは`config.ini`で設定し、CLI指定を優先
- Driver / Data Sourceが公開する設定能力を診断
- 診断結果をJSON/TXTへ保存
- 画像を`./jpeg/DSC_0001.jpeg`形式で連番保存
- 排他的な連番予約で既存画像を上書きしない
- JPEGは一時ファイルへ完成させた後に置換し、途中失敗で壊れた完成ファイルを残しにくくする
- strict / non-strictでDriverの拒否・値調整への扱いを切り替える
- 診断は**read-onlyが既定**。書き込みprobeは明示的に有効化する
- Windows専用。Linux/macOSは対象外

> **Release Candidate**: 自動試験での品質強化は行っていますが、Windows 8 32-bit + fi-65Fでの最終実機確認前です。実機確認完了までは公開版とは扱いません。

## 1. 動作環境

### 1.1 最終運用ターゲット

正本ターゲットは以下です。

- **Windows 8 32-bit (x86)**
- **Python 3.8.10 x86**
- fi-65F用32-bit WIA Driver
- fi-65F用32-bit TWAIN Data Source
- `pytwain==2.3.0`

Pythonが32-bitであることを確認します。

```bat
py -3.8-32 -c "import platform, struct; print(platform.python_version(), struct.calcsize('P') * 8)"
```

想定：

```text
3.8.10 32
```

### 1.2 Windows 8 x86の固定依存関係

最終ターゲットでは、CIで固定している専用requirementsを使用します。

```bat
py -3.8-32 -m pip install -r requirements-win8-x86.txt
```

固定値：

```text
pywin32==308
Pillow==10.4.0
pytwain==2.3.0
```

一般の開発環境では`requirements.txt`を使用できますが、Windows 8 x86の再現試験では固定ファイルを正本とします。

### 1.3 CI環境

GitHub Actionsでは次を確認します。

- Python 3.8.10 / x86 — Windows 8最終環境のPython/bitness/固定依存互換性
- Python 3.11 / x64 — 現行開発環境
- Python 3.12 / x64 — 現行開発環境

各laneでbitness assertion、`pip check`、`compileall`、pytest + coverageを実行します。

GitHub Actions runner自体はWindows 8ではないため、3.8 x86 laneの成功は**Windows 8カーネル、fi-65F Driver、実TWAIN Sourceの動作保証ではありません**。これらは実機試験で確認します。

## 2. 32-bit / 64-bitとTWAIN DSM

### 2.1 WIA

WIA版は`pywin32`からWindows WIA COMを使用します。`scanner_capture.py`は32-bit / 64-bit Windowsの双方を許容します。

最終ターゲット：

```text
Python 3.8.10 x86
        ↓
32-bit WIA / fi-65F Driver
```

### 2.2 TWAIN

TWAINではPythonプロセス、DSM、Data Sourceのbitnessを一致させます。

```text
Python process
      │
      ├── TWAIN DSM
      │
      └── TWAIN Data Source
```

最終ターゲット：

```text
Python 3.8.10 x86      32-bit
TWAIN DSM              32-bit
fi-65F Data Source     32-bit
```

`pytwain 2.3.x`の自動DSM選択を使用する場合、32-bit Windows/TWAIN 1では通常`%WINDIR%\twain_32.dll`を使用します。64-bit Pythonでは通常`twaindsm.dll`を使用します。

そのため、通常は`[twain] dsm_name`を空欄のままにします。DSMを明示するのは自動選択で成立しない場合だけです。

TWAIN診断JSONには、実行中Pythonのbitnessと、明示したDSM名または自動DSMの説明を記録します。

## 3. ファイル構成

```text
scanner_camera/
├─ scanner_capture.py             WIA診断・制御・画像取得
├─ twain_capture.py               TWAIN診断・制御・画像取得
├─ config.ini                     共通設定 + TWAIN固有設定
├─ requirements.txt               一般開発用の実行依存
├─ requirements-dev.txt           一般開発用のテスト依存
├─ requirements-win8-x86.txt      Windows 8 x86固定実行依存
├─ requirements-dev-win8-x86.txt  Windows 8 x86固定テスト依存
├─ README.md
├─ TESTING.md
├─ PUBLIC_RELEASE_CHECKLIST.md
└─ tests/
```

`jpeg/`と`diagnostics/`はローカル生成物であり`.gitignore`対象です。撮影画像、Device ID、Driver情報等を誤って公開しないため、リポジトリへcommitしません。

## 4. コードの責務

### 4.1 `scanner_capture.py` — WIA

主な処理：

1. WIA Scanner列挙・選択
2. WIA Property列挙
3. RANGE / LIST / FLAG / read-only情報の診断
4. 必要に応じたno-change write/read-back probe
5. intent / DPI / brightness / contrast / scan region設定
6. WIA BMP transfer
7. color / grayscale / bw変換
8. JPEGのatomic保存
9. `DSC_####.jpeg`の排他的採番
10. COM objectをスコープ内で破棄してから`CoUninitialize()`

WIAで公開されない物理露光時間・積分時間・アナログゲインをコード側で推測して操作しません。

### 4.2 `twain_capture.py` — TWAIN

主な処理：

1. TWAIN Source Manager生成
2. Data Source列挙・一意選択
3. `CAP_SUPPORTEDCAPS`取得
4. scanner cameraで重要なCapabilityの追加照会
5. `GET` / `GETCURRENT` / `GETDEFAULT` / `MSG_QUERYSUPPORT`
6. 明示時のみno-change SET/read-back probe
7. Pixel Type / Units / X-Y DPI /画質・露出・光源関連Capability設定
8. SET後の`GETCURRENT`確認
9. 実際にread-backしたX/Y DPIでpixel regionを`DAT_IMAGELAYOUT`へ換算
10. native transfer
11. `DAT_IMAGEINFO`で取得できた実X/Y解像度をJPEG DPI metadataへ反映
12. JPEGのatomic保存
13. Source / Source Manager close

TWAINの有効Capability、型、範囲、単位はData Source依存です。fi-65F実機の診断結果を正本として判断します。

## 5. 出力ファイルの整合性

WIA/TWAINは共通して次の保存契約を使います。

```text
./jpeg/DSC_0001.jpeg
./jpeg/DSC_0002.jpeg
./jpeg/DSC_0003.jpeg
```

保存手順：

1. `O_CREAT | O_EXCL`で0-byteの最終ファイル名を予約
2. 同じ出力ディレクトリに一時JPEGを作成
3. JPEG encode完了
4. 一時ファイルをflush/fsync
5. `os.replace()`で予約ファイルを完成JPEGへ置換
6. encode失敗時は一時ファイルを削除し、0-byte予約は上位処理が削除

これにより、JPEG encode途中の部分ファイルを正常な`DSC_####.jpeg`として残すことを避けます。

## 6. 診断はread-onlyが既定

`config.ini`の既定値：

```ini
[diagnostics]
probe_writes = false
```

したがって通常の診断はDriver/Data SourceへSETしません。

```bat
py -3.8-32 scanner_capture.py --device fi-65F --diagnose
py -3.8-32 twain_capture.py --device fi-65F --diagnose
```

Sourceが安定していることを確認後、no-change write/read-back probeを明示的に行う場合だけ`--probe-writes`を付けます。

```bat
py -3.8-32 scanner_capture.py --device fi-65F --diagnose --probe-writes
py -3.8-32 twain_capture.py --device fi-65F --diagnose --probe-writes
```

`--no-probe-writes`は、ローカル`config.ini`が`true`でもCLIから強制的に無効化するために残しています。`--probe-writes`と`--no-probe-writes`の同時指定は設定エラーです。

## 7. WIA利用方法

### 7.1 デバイス確認

```bat
py -3.8-32 scanner_capture.py --list-devices
```

### 7.2 診断

```bat
py -3.8-32 scanner_capture.py --device fi-65F --diagnose
```

出力：

```text
./diagnostics/wia_diagnostic_YYYYMMDD_HHMMSS.json
./diagnostics/wia_diagnostic_YYYYMMDD_HHMMSS.txt
```

64-bit開発機でのfi-65F実測では以下を確認済みです。

- X/Y解像度: 75～600 dpi
- brightness: -128～127
- contrast: -128～127
- threshold: 1～255
- 24 bit RGB出力

これは64-bit WIA環境の実測であり、Windows 8 x86では再診断します。

### 7.3 取り込み

```bat
py -3.8-32 scanner_capture.py ^
  --device fi-65F ^
  --dpi 600 ^
  --mode color ^
  --brightness -128 ^
  --contrast 0
```

## 8. TWAIN利用方法

### 8.1 Source確認

```bat
py -3.8-32 twain_capture.py --list-devices
```

fi-65Fが見えない場合は、Python / DSM / Data Sourceのbitnessと32-bit Data Sourceの導入状態を確認します。

### 8.2 read-only診断

```bat
py -3.8-32 twain_capture.py --device fi-65F --diagnose
```

出力：

```text
./diagnostics/twain_diagnostic_YYYYMMDD_HHMMSS.json
./diagnostics/twain_diagnostic_YYYYMMDD_HHMMSS.txt
```

write probeは別段階で実施します。

```bat
py -3.8-32 twain_capture.py --device fi-65F --diagnose --probe-writes
```

### 8.3 重点Capability

基本画像設定：

- `ICAP_PIXELTYPE`
- `ICAP_XRESOLUTION` / `ICAP_YRESOLUTION`
- `ICAP_BITDEPTH`
- `ICAP_BRIGHTNESS`
- `ICAP_CONTRAST`
- `ICAP_THRESHOLD`
- `ICAP_UNITS`
- `ICAP_XFERMECH`

scanner cameraで特に確認するもの：

- `ICAP_AUTOBRIGHT`
- `ICAP_EXPOSURETIME`
- `ICAP_GAMMA`
- `ICAP_HIGHLIGHT`
- `ICAP_SHADOW`
- `ICAP_LAMPSTATE`
- `ICAP_LIGHTSOURCE`
- `ICAP_LIGHTPATH`
- `ICAP_PHYSICALWIDTH` / `ICAP_PHYSICALHEIGHT`
- `ICAP_XNATIVERESOLUTION` / `ICAP_YNATIVERESOLUTION`
- `DAT_IMAGELAYOUT`

TWAIN仕様にCapabilityが存在しても、fi-65F Data Sourceが実装しているとは限りません。

### 8.4 基本取り込み

```bat
py -3.8-32 twain_capture.py ^
  --device fi-65F ^
  --dpi 600 ^
  --mode color ^
  --brightness -128 ^
  --contrast 0
```

### 8.5 TWAIN固有設定

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

- `--autobright on|off`
- `--exposure-time <value>`
- `--gamma <value>`
- `--lamp-state on|off`
- `--light-source <raw-value>`
- `--bit-depth <value>`

`autobright` / `lamp_state`は`on`または`off`だけを許容します。`falsee`等のタイプミスを黙ってOFFとして扱いません。

## 9. strict / non-strict

既定：

```ini
[scanner]
strict_settings = true
```

strictでは、要求した設定について以下をエラーとして扱います。

- Capability / Propertyが存在しない
- read-only / SET拒否
- SET後のread-back不能
- TWAIN Sourceが要求値と異なる値をread-back
- pixel region設定時にunitsまたは実DPIを確認できない

TWAIN `TWTY_FIX32`だけは16.16固定小数点の1 LSB相当を丸め誤差として許容します。

non-strict：

```bat
py -3.8-32 twain_capture.py --non-strict
```

non-strictでは警告して可能な範囲で続行します。特にDPIがSource側で調整された場合は、**要求値ではなくread-backされた実DPI**を後続のregion換算へ使います。実DPIが確認できない場合、pixel region設定は安全のためスキップします。

## 10. 読み取り範囲

WIA/TWAINともCLIではpixel単位で指定します。

```bat
--xpos 0 --ypos 0 --width 2480 --height 3496
```

- WIA: WIA Propertyへpixel値を設定
- TWAIN: `ICAP_UNITS=inches`を確認し、Sourceからread-backしたX/Y DPIを使って`DAT_IMAGELAYOUT`へ換算

X方向とY方向の解像度が異なる場合も別々に換算します。

## 11. 露出・LED制御の位置づけ

WIAで公開された`brightness`はfi-65F実機で画像変化を確認済みですが、物理的なCIS積分時間や露光時間そのものとは断定していません。

TWAINでは次を追加診断します。

- `ICAP_AUTOBRIGHT`
- `ICAP_EXPOSURETIME`
- `ICAP_GAMMA`
- `ICAP_LAMPSTATE`
- `ICAP_LIGHTSOURCE`
- `ICAP_LIGHTPATH`

Windows 8 x86 + 32-bit fi-65F Data Sourceでの公開状況は実機診断で判断します。`ICAP_LAMPSTATE`等が公開されない、またはSET不能なら、内蔵LED停止はハード側改造の課題として扱います。

## 12. テスト

一般開発環境：

```bat
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q scanner_capture.py twain_capture.py tests
python -m pytest --cov=scanner_capture --cov=twain_capture --cov-report=term-missing
```

Windows 8 x86固定環境：

```bat
py -3.8-32 -m pip install -r requirements-dev-win8-x86.txt
py -3.8-32 -m pip check
py -3.8-32 -m compileall -q scanner_capture.py twain_capture.py tests
py -3.8-32 -m pytest
```

詳細な責務分界と実機試験手順は`TESTING.md`を参照してください。

## 13. 既知の検証境界

CIだけでは保証しない項目：

- Windows 8カーネル上でのPython 3.8 / pywin32 / Pillow / pytwain実動作
- fi-65F 32-bit WIA Driver
- fi-65F 32-bit TWAIN Data Source
- 実DSM/Data Sourceの組み合わせ
- PaperStream固有Capability
- 実native transfer
- LED制御
- 露光時間・積分時間
- 実画像のS/N・色・ダイナミックレンジ
- LED/導光系改造後の動作

## 14. 公開前のライセンス確認

このリポジトリを公開する前に、プロジェクト自身の`LICENSE`を決定し、使用している依存パッケージのライセンス条件との整合を確認します。

特に`pytwain==2.3.0`を含むため、公開方法・配布方法を決める段階で依存ライセンスを再確認してください。現時点ではリポジトリのライセンスを自動的に決めません。

公開判定条件は`PUBLIC_RELEASE_CHECKLIST.md`で管理します。
