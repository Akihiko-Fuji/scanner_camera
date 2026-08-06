# fi-65F WIA Capture CLI v0.2

64-bit Windows専用のfi-65F取り込み試作ツールです。Linux/macOSは対象外です。

- CLIまたは`config.ini`で設定
- WIAプロパティ診断
- 対象設定の公開・読み取り専用・書き込み可否を判定
- 全WIAプロパティをJSON/TXTに保存
- 画像を`./jpeg/DSC_0001.jpeg`形式で連番保存

## 1. セットアップ

64-bit Pythonを使用してください。

```bat
py -c "import struct; print(struct.calcsize('P') * 8)"
py -m pip install -r requirements.txt
```

最初のコマンドが`64`になっていることを確認します。

## 2. デバイス確認

```bat
py scanner_capture.py --list-devices
```

## 3. WIA診断

```bat
py scanner_capture.py --device fi-65F --diagnose
```

結果は以下へ保存されます。

```text
./diagnostics/wia_diagnostic_YYYYMMDD_HHMMSS.json
./diagnostics/wia_diagnostic_YYYYMMDD_HHMMSS.txt
```

診断では、対象設定ごとに次の状態を出します。

- `NOT_EXPOSED_BY_WIA`
- `EXPOSED_READ_ONLY`
- `EXPOSED_AND_SETTABLE`
- `EXPOSED_WRITABLE_NOT_PROBED`
- `EXPOSED_BUT_WRITE_REJECTED`
- `EXPOSED_SUPPORT_UNCERTAIN`

通常の診断では、読み書き可能と宣言されたプロパティに現在値を再設定し、読み戻せるかを確認します。設定値そのものは変更しません。書き込み確認を避ける場合は次を使います。

```bat
py scanner_capture.py --diagnose --no-probe-writes
```

診断対象には以下を含みます。

- カラーモード
- X/Y解像度
- 読み取り位置・範囲
- brightness
- contrast
- orientation
- rotation
- mirror
- threshold
- invert
- warm-up time

加えて、名称が不明なメーカー独自項目を含め、選択されたWIA項目が公開する全プロパティを出力します。

## 4. config.iniで取り込み

```bat
py scanner_capture.py --config config.ini
```

出力例：

```text
./jpeg/DSC_0001.jpeg
./jpeg/DSC_0002.jpeg
```

既存の最大番号に1を加えます。`DSC_9999.jpeg`まで使用するとエラーになります。

## 5. CLIで設定を上書き

```bat
py scanner_capture.py ^
  --device fi-65F ^
  --dpi 600 ^
  --mode color ^
  --brightness 500 ^
  --contrast 0 ^
  --jpeg-quality 95 ^
  --output-dir .\jpeg
```

CLI指定が`config.ini`より優先されます。

## 6. 未対応設定の扱い

`strict_settings = true`では、指定した設定がWIAに公開されていない、読み取り専用、または書き込み拒否の場合に取り込みを中止します。診断結果との食い違いを見逃さないための動作です。

警告だけで続行する場合：

```bat
py scanner_capture.py --non-strict
```

## 7. 露出制御について

WIAの`brightness`と`contrast`はドライバーが公開するハードウェア設定です。ただし、物理的な露光時間、CIS積分時間、アナログゲインに直結する保証はありません。

診断結果で露出相当のメーカー独自プロパティが見つからず、brightnessを変更しても画像に有効な差が出ない場合は、次段階としてTWAIN Capabilityの列挙・設定が必要です。
