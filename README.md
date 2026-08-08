# fi-65F Scanner Camera CLI v0.3

64-bit Windows専用のfi-65F取り込み・診断ツールです。Linux/macOSは対象外です。

現在は2系統を並行して保持します。

- `scanner_capture.py`: WIA診断 + WIA制御
- `twain_capture.py`: TWAIN Capability診断 + TWAIN制御

共通仕様：

- CLIまたは`config.ini`で設定
- 診断結果をJSON/TXTへ保存
- 設定の公開・読み取り・書き込み可否を調査
- 画像を`./jpeg/DSC_0001.jpeg`形式で連番保存
- CLI指定を`config.ini`より優先
- Windows 64-bitのみ対象

## 1. セットアップ

64-bit Pythonを使用してください。

```bat
py -c "import struct; print(struct.calcsize('P') * 8)"
py -m pip install -r requirements.txt
```

最初のコマンドが`64`になっていることを確認します。

TWAIN版は`pytwain`を使用します。64-bit PythonからTWAINを使用するため、64-bit `TWAINDSM.dll`と64-bit TWAIN Data Sourceが必要です。`twain_capture.py --list-devices`でSourceが列挙されなければ、DSMとドライバーのbitnessを最初に確認してください。

## 2. WIA

### デバイス確認

```bat
py scanner_capture.py --list-devices
```

### WIA診断

```bat
py scanner_capture.py --device fi-65F --diagnose
```

出力：

```text
./diagnostics/wia_diagnostic_YYYYMMDD_HHMMSS.json
./diagnostics/wia_diagnostic_YYYYMMDD_HHMMSS.txt
```

### WIA取り込み

```bat
py scanner_capture.py ^
  --device fi-65F ^
  --dpi 600 ^
  --mode color ^
  --brightness -128 ^
  --contrast 0
```

## 3. TWAIN

### Source確認

```bat
py twain_capture.py --list-devices
```

fi-65Fが列挙されたら、Source名の一部を`--device`へ指定できます。

### TWAIN診断

```bat
py twain_capture.py --device fi-65F --diagnose
```

出力：

```text
./diagnostics/twain_diagnostic_YYYYMMDD_HHMMSS.json
./diagnostics/twain_diagnostic_YYYYMMDD_HHMMSS.txt
```

診断では`CAP_SUPPORTEDCAPS`を起点に、Sourceが公開するCapabilityを読み取ります。scanner camera用途では特に以下を重点確認します。

- `ICAP_PIXELTYPE`
- `ICAP_XRESOLUTION` / `ICAP_YRESOLUTION`
- `ICAP_BRIGHTNESS`
- `ICAP_CONTRAST`
- `ICAP_THRESHOLD`
- `ICAP_AUTOBRIGHT`
- `ICAP_EXPOSURETIME`
- `ICAP_GAMMA`
- `ICAP_HIGHLIGHT` / `ICAP_SHADOW`
- `ICAP_LAMPSTATE`
- `ICAP_LIGHTSOURCE`
- `ICAP_LIGHTPATH`
- `ICAP_BITDEPTH`
- `ICAP_PHYSICALWIDTH` / `ICAP_PHYSICALHEIGHT`
- `ICAP_XNATIVERESOLUTION` / `ICAP_YNATIVERESOLUTION`
- `ICAP_UNITS`
- `ICAP_XFERMECH`
- `DAT_IMAGELAYOUT`

通常の診断では、上記のうちscanner_cameraで意味のある設定Capabilityに対して「現在値を同じ値でSET→再読込」するno-change write probeを行います。Source全Capabilityへの一律SETは副作用を避けるため行いません。

書き込み確認を避ける場合：

```bat
py twain_capture.py --device fi-65F --diagnose --no-probe-writes
```

### TWAIN取り込み

WIA版と同じ基本引数を使えます。

```bat
py twain_capture.py ^
  --device fi-65F ^
  --dpi 600 ^
  --mode color ^
  --brightness -128 ^
  --contrast 0
```

TWAIN固有のCapabilityが診断で`EXPOSED_AND_SETTABLE`になった場合は、追加設定も指定できます。

```bat
py twain_capture.py ^
  --device fi-65F ^
  --dpi 600 ^
  --mode color ^
  --autobright off ^
  --exposure-time 1.0 ^
  --gamma 1.0 ^
  --lamp-state off
```

`--exposure-time`、`--gamma`などの単位・有効範囲はData Source依存です。必ず`--diagnose`の`allowed/current/default`を確認してから指定してください。

## 4. 読み取り範囲

WIA/TWAINともCLIでは同じピクセル単位の指定を使います。

```bat
--xpos 0 --ypos 0 --width 2480 --height 3496
```

- WIA: WIAプロパティへピクセル値として設定
- TWAIN: 指定DPIからインチへ換算し`DAT_IMAGELAYOUT`へ設定

空欄ならSource/Driverの現在の読み取り範囲を維持します。

## 5. config.ini

```bat
py scanner_capture.py --config config.ini
py twain_capture.py --config config.ini
```

`[scan]`、`[region]`、`[output]`は両系統で共用します。TWAIN固有設定は`[twain]`へ記載します。

```ini
[twain]
dsm_name =
autobright =
exposure_time =
gamma =
lamp_state =
light_source =
bit_depth =
```

空欄は「Sourceの現在値を維持」を意味します。

## 6. 未対応設定の扱い

`strict_settings = true`では、指定した設定がSource/Driverに公開されていない、またはSETに失敗した場合に取り込みを中止します。

警告だけで続行する場合：

```bat
py twain_capture.py --non-strict
```

## 7. 出力

両系統とも同じ採番処理を使います。

```text
./jpeg/DSC_0001.jpeg
./jpeg/DSC_0002.jpeg
./jpeg/DSC_0003.jpeg
```

既存最大番号に1を加え、排他的にファイルを予約します。`DSC_9999.jpeg`まで使用するとエラーになります。

## 8. 露出・LED制御の位置づけ

WIAで公開された`brightness`はfi-65F実機で設定・画像変化を確認済みですが、物理露光時間やCIS積分時間に直結するとは限りません。

TWAINではWIAに存在しなかった以下の標準CapabilityがSourceから公開される可能性があります。

- `ICAP_AUTOBRIGHT`
- `ICAP_EXPOSURETIME`
- `ICAP_GAMMA`
- `ICAP_LAMPSTATE`
- `ICAP_LIGHTSOURCE`
- `ICAP_LIGHTPATH`

ただし、TWAIN標準にCapabilityが定義されていることと、fi-65F/PaperStream Data Sourceが実装していることは別です。実機の`twain_diagnostic_*.json/.txt`を正本として判断します。

LED制御Capabilityが公開されない場合は、LED停止はハード側改造の対象とします。

## 9. テスト

```bat
python -m pytest --cov=scanner_capture --cov=twain_capture --cov-report=term-missing
```

GitHub ActionsではWindows x64 + Python 3.11/3.12で、実機を必要としないWIA/TWAINロジックを検証します。Data Source列挙、実Capability値、実スキャンは実機確認対象です。

詳細は`TESTING.md`を参照してください。

## 10. 参考

- TWAIN 2.x Specification: https://twain.org/specification/
- pytwain: https://pypi.org/project/pytwain/
