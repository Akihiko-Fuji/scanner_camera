# テスト方針

本プロジェクトはWindows専用で、WIAとTWAINの2経路を持つ。最終運用ターゲットは**Windows 8 32-bit + Python 3.8.10 x86**とする。

検証を次の4層へ分ける。

1. 純粋ロジック・テストダブルによる単体テスト
2. Python 3.8 x86 / 3.11 x64 / 3.12 x64 CI
3. Windows 8 32-bit + fi-65F実機試験
4. 公開前Release Candidate判定

CIの成功だけでは実機動作・公開可否を判定しない。

## 1. 対象環境

### 1.1 最終ターゲット

- Windows 8 32-bit
- Python 3.8.10 x86
- fi-65F 32-bit WIA Driver
- fi-65F 32-bit TWAIN Data Source
- `pytwain==2.3.0`

TWAINはbitnessを一致させる。

```text
Python process      32-bit
TWAIN DSM           32-bit
TWAIN Data Source   32-bit
```

32-bit環境でpytwainの自動DSM選択を使う場合は、通常Windowsの`%WINDIR%\twain_32.dll`経路を使用する。明示DSM指定は自動選択で成立しない場合に限定する。

### 1.2 CI互換環境

GitHub Actions：

- Python 3.8 / x86
- Python 3.11 / x64
- Python 3.12 / x64

Python 3.8 x86 laneは`requirements-dev-win8-x86.txt`を使用し、Windows 8用に固定した依存セットを検証する。

各laneで以下を実施する。

1. pointer sizeによるbitness assertion
2. dependency install
3. `python -m pip check`
4. `python -m compileall`
5. pytest + coverage

GitHub Actions runnerはWindows 8ではないため、x86 lane成功だけでWindows 8上のCOM/TWAIN/Driver実動作を保証しない。

## 2. 共通の自動試験契約

- CLI指定を`config.ini`より優先する
- `DSC_####.jpeg`を既存最大番号の次で採番する
- `O_EXCL`による予約で既存画像を上書きしない
- JPEG encodeは同一ディレクトリの一時ファイルへ行い、完成後に`os.replace()`する
- encode失敗時に部分JPEGを完成ファイルとして残さない
- 取り込み失敗時は0-byte予約を削除する
- color / grayscale / bwを維持する
- bwは128 thresholdで二値化する
- strictは未対応、SET失敗、read-back不能、不一致を失敗にする
- non-strictは警告して安全に継続する
- 診断はread-onlyを既定とする
- write probeは`--probe-writes`で明示的に有効化する
- `--probe-writes`と`--no-probe-writes`の同時指定を拒否する
- `jpeg/` / `diagnostics/`はGit管理対象外とする

## 3. WIA自動テスト

COM/WIAをテストダブルへ置き換え、以下を検証する。

- Scanner列挙と名前選択
- Property制約のRANGE / LIST / FLAG解釈
- read-only判定
- 全Property診断と対象Property support判定
- read-only既定診断
- 明示的no-change write/read-back probe
- unsupported / read-only / SET失敗時のstrict / non-strict
- Driverが正規化した値のread-back
- DPI / mode / brightness / contrast / scan region
- WIA transfer
- color / grayscale / bw JPEG
- atomic JPEG成功・失敗
- `DSC_####.jpeg`採番
- 失敗時予約削除
- COM `CoInitialize()` / `CoUninitialize()`
- **WIA COM proxyを保持する処理スコープの終了とGCが`CoUninitialize()`より先であること**
- 32-bit Windows runtimeを拒否しないこと

実機では、以前観測された`Win32 exception occurred releasing IUnknown`が再発しないことを別途確認する。

## 4. TWAIN自動テスト

### 4.1 Source Manager / Source選択

- Source Manager Identity
- DSM明示指定
- process bitness判定
- 32-bit自動DSM説明に`twain_32.dll`が現れること
- Source一覧
- case-insensitive部分一致
- 一致なし / 曖昧一致 / open失敗
- Source / Source Manager close

### 4.2 Capability診断

- ONEVALUE相当値の正規化
- RANGEからCurrentValue抽出
- ENUMERATIONからCurrentIndex抽出
- `CAP_SUPPORTEDCAPS`
- `GET`
- `GETCURRENT`
- `GETDEFAULT`
- `MSG_QUERYSUPPORT`
- 読み出し失敗の診断化
- 未公開Capability
- read-only既定診断
- 明示的no-change SET/read-back probe
- scalarでないCurrentValueをSETしない
- scanner_camera対象外Capabilityへ無差別SETしない
- SET拒否
- no-change SET後の値調整

重点Capability：

- `ICAP_PIXELTYPE`
- `ICAP_XRESOLUTION` / `ICAP_YRESOLUTION`
- `ICAP_BRIGHTNESS`
- `ICAP_CONTRAST`
- `ICAP_THRESHOLD`
- `ICAP_BITDEPTH`
- `ICAP_AUTOBRIGHT`
- `ICAP_EXPOSURETIME`
- `ICAP_GAMMA`
- `ICAP_HIGHLIGHT` / `ICAP_SHADOW`
- `ICAP_LAMPSTATE`
- `ICAP_LIGHTSOURCE`
- `ICAP_LIGHTPATH`
- `ICAP_UNITS`
- `ICAP_XFERMECH`

### 4.3 SET / read-back契約

- Data SourceのCurrent ItemTypeを優先
- ItemType不明時のフォールバック
- SET後に必ず`GETCURRENT`を確認
- strict: SET拒否で失敗
- strict: `GETCURRENT`不能で失敗
- strict: 要求値とread-back不一致で失敗
- non-strict: SET拒否を警告
- non-strict: read-back不能を警告
- non-strict: 値調整を警告し、確認できた実値を後続処理へ渡す
- `TWTY_FIX32`は16.16固定小数点1 LSB相当だけ許容
- `autobright` / `lamp_state`は`on` / `off`以外を設定エラーにする

### 4.4 `DAT_IMAGELAYOUT`

- current/default layout取得
- 明示的no-change SET probe
- SET拒否
- `ICAP_UNITS=inches`のread-back確認
- X/Y DPIをそれぞれread-back
- pixel→inch換算に**要求DPIではなく実read-back DPI**を使用
- X/Y DPIが異なる場合に別々に換算
- actual units / DPI不明時はunsafeなregion設定をしない
- layout read/write失敗

### 4.5 native transfer / JPEG

- native transfer callback
- first imageだけ保存
- Twain image object close
- no image error
- color / grayscale / bw
- bw threshold
- JPEG quality clamp
- `DAT_IMAGEINFO`の`XResolution` / `YResolution`をJPEG DPI metadataへ反映
- `DAT_IMAGEINFO`が取得できない場合のfallback
- atomic JPEG保存
- 失敗時予約cleanup

## 5. 自動テストの実行

### 5.1 一般開発環境

```bat
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q scanner_capture.py twain_capture.py tests
python -m pytest --cov=scanner_capture --cov=twain_capture --cov-report=term-missing
```

### 5.2 Windows 8 x86固定依存

```bat
py -3.8-32 -m pip install -r requirements-dev-win8-x86.txt
py -3.8-32 -m pip check
py -3.8-32 -m compileall -q scanner_capture.py twain_capture.py tests
py -3.8-32 -m pytest
```

固定runtime：

```text
pywin32==308
Pillow==10.4.0
pytwain==2.3.0
```

## 6. Windows 8 32-bit実機試験

この章を通過して初めて、最終運用環境で「動作確認済み」とする。

### 6.1 Python / dependency確認

```bat
py -3.8-32 -c "import platform, struct; print(platform.python_version(), struct.calcsize('P') * 8)"
py -3.8-32 -m pip install -r requirements-win8-x86.txt
py -3.8-32 -m pip check
py -3.8-32 -c "import win32com.client, PIL, twain; print('OK')"
```

期待：

```text
3.8.10 32
OK
```

### 6.2 WIA — 列挙

```bat
py -3.8-32 scanner_capture.py --list-devices
```

確認：fi-65Fが一意に列挙される。

### 6.3 WIA — read-only診断

```bat
py -3.8-32 scanner_capture.py --device fi-65F --diagnose
```

確認：

- JSON/TXT生成
- `probe_writes=false`
- DPI / brightness / contrast / thresholdの公開状態
- Driver/Device ID
- 診断のみでスキャン・意図しない設定変更が起きない

### 6.4 WIA — 明示write probe

read-only診断が安定した後だけ実施する。

```bat
py -3.8-32 scanner_capture.py --device fi-65F --diagnose --probe-writes
```

確認：no-change SET/read-backとDriverの応答。

### 6.5 WIA — 実取得

```bat
py -3.8-32 scanner_capture.py --device fi-65F --dpi 600 --mode color --brightness 0 --contrast 0
```

確認：

- `DSC_####.jpeg`が0 byteでない
- JPEGとして再オープンできる
- 期待する画像寸法
- Scannerが正常終了する
- **終了時に`Win32 exception occurred releasing IUnknown`が出ない**
- 連続3回以上でCOM関連warning/異常終了がない

## 7. TWAIN 32-bit実機試験

### 7.1 Source列挙

```bat
py -3.8-32 twain_capture.py --list-devices
```

確認：

- fi-65F 32-bit Data Sourceが列挙される
- Source未検出時の診断文が32-bit Pythonと自動DSMを正しく示す

通常はDSMを明示せず、pytwainの自動選択から開始する。

### 7.2 TWAIN read-only診断

```bat
py -3.8-32 twain_capture.py --device fi-65F --diagnose
```

重点確認：

- `environment.python_bitness == 32`
- DSM表示
- `CAP_SUPPORTEDCAPS`
- `ICAP_PIXELTYPE`
- `ICAP_XRESOLUTION` / `ICAP_YRESOLUTION`
- `ICAP_BRIGHTNESS` / `ICAP_CONTRAST`
- `ICAP_AUTOBRIGHT`
- `ICAP_EXPOSURETIME`
- `ICAP_GAMMA`
- `ICAP_LAMPSTATE`
- `ICAP_LIGHTSOURCE`
- `ICAP_LIGHTPATH`
- `ICAP_BITDEPTH`
- `DAT_IMAGELAYOUT`
- `probe_writes=false`

### 7.3 TWAIN明示write probe

read-only診断が安定した後だけ実施する。

```bat
py -3.8-32 twain_capture.py --device fi-65F --diagnose --probe-writes
```

対象Capabilityだけを現在値で再SETする。全Capabilityには書き込まない。

### 7.4 WIAと同条件のTWAIN取得

```bat
py -3.8-32 twain_capture.py --device fi-65F --dpi 600 --mode color --brightness -128 --contrast 0
```

確認：

- JPEG生成
- 実画像寸法
- `DAT_IMAGEINFO` X/Y resolutionログ
- JPEG DPI metadataが実解像度と一致
- WIAとの明るさ・色・階調差
- 所要時間
- UIなしで終了
- Source/DSMが次回実行で正常に再openできる

### 7.5 SourceによるDPI調整試験

Sourceが要求DPIを丸めるケースが作れる場合、`--non-strict`で確認する。

確認：

- warningにrequested/read-backが出る
- region指定はread-back DPIで換算される
- JPEG DPIは`DAT_IMAGEINFO`の実値を優先する

### 7.6 TWAIN固有Capability

診断でSET可能と確認された場合だけ実施する。

```bat
py -3.8-32 twain_capture.py --device fi-65F --lamp-state off
py -3.8-32 twain_capture.py --device fi-65F --autobright off --exposure-time <許可値>
```

`ICAP_LAMPSTATE`が未公開/SET不能ならLED停止はハード側課題として扱う。

`ICAP_EXPOSURETIME`が公開された場合は画像平均輝度だけではなく、飽和、暗部S/N、走査時間の変化を記録し、単なるデジタルbrightnessとの違いを評価する。

## 8. ハード改造後の再試験

LED/導光系を変更した後は最低限以下を再実施する。

- WIA read-only診断
- WIA実取得
- TWAIN read-only診断
- TWAIN実取得
- LED光漏れ確認
- 外部投影像の結像確認
- 複数回連続取得
- Scanner再起動後の再接続

## 9. CIで保証しないこと

- Windows 8カーネル上の実動作
- fi-65F 32-bit WIA Driver
- fi-65F 32-bit TWAIN Data Source
- PaperStream固有Capability
- DSM/Data Source固有の状態遷移・副作用
- 実native transfer
- LEDソフト制御可否
- CIS積分時間・走査時間
- S/N、ダイナミックレンジ、色再現
- ハード改造後の挙動

## 10. Release Candidate判定

公開候補へ進むには以下をすべて満たす。

- 3系統CIが同じHEADでcompleted/success
- x86 laneが固定requirementsを実使用
- WIA実機列挙・read-only診断・実取得成功
- TWAIN実機列挙・read-only診断・実取得成功
- WIA COM解放warningが再発しない
- 連続取得で壊れたJPEG・0-byte残留がない
- READMEの実測値を実機結果へ更新
- 診断JSON/TXTに公開してはいけない個人情報・機密情報がないことを確認
- project LICENSEと依存ライセンスの扱いを確定

詳細は`PUBLIC_RELEASE_CHECKLIST.md`で記録する。

## 11. 再確認トリガー

以下の変更時は実機確認を再実施する。

- WIA/TWAIN/PaperStream Driver更新
- TWAIN DSM変更
- Python 3.8環境変更
- `requirements-win8-x86.txt`変更
- pywin32/Pillow/pytwain更新
- Capability設定順変更
- strict/non-strict契約変更
- region換算変更
- native transfer callback変更
- JPEG保存方式変更
- COM lifecycle変更
- LED/導光系ハード改造
