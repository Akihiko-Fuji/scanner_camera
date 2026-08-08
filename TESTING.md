# テスト方針

本プロジェクトは64-bit Windowsを実行環境とし、WIAとTWAINの2経路を持つ。通常のCIではfi-65F実機を接続できないため、テストを「自動単体テスト」と「実機確認」に分ける。

目的は単なる行カバレッジではなく、WIA/TWAINのどちらを使っても同じCLI契約、同じ保存契約、同じ失敗時挙動を維持することである。

## 1. 自動単体テスト

### 1.1 共通契約

- `config.ini`よりCLI指定を優先する
- `DSC_####.jpeg`を既存最大番号の次で採番する
- 排他的なファイル予約で上書きを避ける
- 取り込み失敗時は空の予約ファイルだけ削除する
- JPEG qualityを有効範囲へ収める
- color / grayscale / bwの出力モードを維持する
- strictでは未対応設定をエラーとする
- non-strictでは警告して継続する
- 診断と通常取得で出力ディレクトリを分離する

### 1.2 WIA

COM/WIAオブジェクトをテストダブルへ置き換え、以下を検証する。

- WIA Scanner列挙と選択
- WIA Property制約のRANGE / LIST / FLAG解釈
- read-only判定
- 対象Property診断ステータス
- no-change write/read-back probe
- unsupported / read-only / SET失敗時のstrict / non-strict
- DPI / mode / brightness / contrast / scan region設定
- WIA転送
- color / grayscale / bw JPEG
- 診断CLIフロー
- 通常取得CLIフロー
- COM初期化 / 解放
- 失敗時の予約ファイル後始末

### 1.3 TWAIN

TWAIN Data SourceとSource Managerをテストダブルへ置き換え、WIA側と同等の責務まで検証する。

#### Source Manager / Source選択

- Source Manager生成時のアプリケーションIdentity
- DSM明示指定
- Source一覧取得
- Source名の大文字小文字を無視した部分一致
- 未指定時の先頭Source選択
- 一致なし
- 曖昧一致拒否
- Source open失敗
- 正常終了・異常終了時のSource / Source Manager close

#### Capability診断

- pytwain戻り値のONEVALUE相当正規化
- RANGE相当からCurrentValue抽出
- ENUMERATION相当からCurrentIndexの値抽出
- `CAP_SUPPORTEDCAPS`解析
- `GET`
- `GETCURRENT`
- `GETDEFAULT`
- `MSG_QUERYSUPPORT`
- 取得失敗時の安全な診断化
- Sourceが公開しないCapabilityの判定
- no-change SET/read-back probe
- SET拒否の判定
- scalarでないCurrentValueを無理にSETしないこと
- scanner_camera対象外Capabilityを一律SETしないこと
- TWAIN定数がpytwain側に存在しない場合の診断

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

#### TWAIN設定

- pixel typeとcolor / grayscale / bwの対応
- Data Sourceが返すItemTypeを優先してSET
- ItemType不明時の型フォールバック
- DPI設定
- brightness / contrast
- autobright
- exposure time
- gamma
- lamp state
- light source
- bit depth
- strict / non-strict

#### DAT_IMAGELAYOUT

- 現在layout取得
- default layout取得
- no-change SET probe
- SET拒否判定
- ピクセル値からインチへの換算
- xpos / ypos / width / heightの部分指定
- layout read失敗
- layout write失敗

#### 画像取得と保存

- native transfer callback
- 最初の画像だけ保存すること
- TWAIN image objectのclose
- 画像が返らなかった場合のエラー
- color / grayscale / bw JPEG
- JPEG DPIメタデータ
- quality clamp
- `DSC_####.jpeg`採番
- 失敗時の空予約ファイル削除

#### CLI統合

- Windows以外を拒否
- 32-bit Pythonを拒否
- 実行時依存不足を拒否
- `--list-devices`
- `--diagnose`
- `--no-probe-writes`
- TWAIN固有CLI引数
- 通常取得
- CLI値が設定適用層へ渡ること
- 正常・異常終了時のリソース解放

## 2. 自動テストの実行

開発依存関係をインストールする。

```bat
python -m pip install -r requirements-dev.txt
```

全テスト：

```bat
python -m pytest
```

カバレッジ：

```bat
python -m pytest ^
  --cov=scanner_capture ^
  --cov=twain_capture ^
  --cov-report=term-missing
```

GitHub Actionsでは`actions/setup-python`がPATHへ配置したPythonを確実に使用するため、Windowsの`py`ランチャーではなく`python -m ...`で実行する。

CIマトリクス：

- Windows x64
- Python 3.11
- Python 3.12

CIではfi-65F、PaperStream、実TWAIN DSM/Data Sourceを要求しない。

## 3. 実機確認: WIA

fi-65Fを接続した64-bit Windowsで確認する。

1. Scanner列挙

```bat
py scanner_capture.py --list-devices
```

2. WIA診断

```bat
py scanner_capture.py --device fi-65F --diagnose
```

3. brightness、contrast、解像度の公開範囲を確認

4. brightness最小・中央・最大で各1枚取り込み

5. `./jpeg/DSC_####.jpeg`の生成、画像差、スキャン完了を確認

2026-08-07時点の実機確認では、Python 3.9.13 64-bitからfi-65FをWIA認識し、75～600 dpi、brightness/contrast -128～127の公開とSET/read-backを確認済み。

## 4. 実機確認: TWAIN

TWAIN版は次の順序で確認する。最初の診断ではハード改造やLED停止を行わない。

### 4.1 64-bit Python確認

```bat
py -c "import struct; print(struct.calcsize('P') * 8)"
```

### 4.2 TWAIN Source列挙

```bat
py twain_capture.py --list-devices
```

Sourceが見えない場合はPython / DSM / Data Sourceのbitnessを確認する。

### 4.3 write probeなしで初回診断

```bat
py twain_capture.py --device fi-65F --diagnose --no-probe-writes
```

JSON/TXTで以下を重点確認する。

- `ICAP_PIXELTYPE`
- `ICAP_XRESOLUTION` / `ICAP_YRESOLUTION`
- `ICAP_BRIGHTNESS`
- `ICAP_CONTRAST`
- `ICAP_AUTOBRIGHT`
- `ICAP_EXPOSURETIME`
- `ICAP_GAMMA`
- `ICAP_LAMPSTATE`
- `ICAP_LIGHTSOURCE`
- `ICAP_LIGHTPATH`
- `ICAP_BITDEPTH`
- `DAT_IMAGELAYOUT`

### 4.4 no-change write probe

Sourceが安定して応答したら実施する。

```bat
py twain_capture.py --device fi-65F --diagnose
```

現在値を同じ値で再SETする対象だけをprobeし、Source全Capabilityには書き込まない。

### 4.5 WIAと同条件の基本取り込み

```bat
py twain_capture.py --device fi-65F --dpi 600 --mode color --brightness -128 --contrast 0
```

確認項目：

- `DSC_####.jpeg`生成
- 600 dpi
- 画像寸法
- WIA画像との明るさ・色・階調差
- スキャン所要時間
- Data Source UIを出さない状態で完了すること

### 4.6 TWAIN固有Capability試験

診断でSET可能と確認された場合だけ個別に実施する。

```bat
py twain_capture.py --device fi-65F --lamp-state off
py twain_capture.py --device fi-65F --autobright off --exposure-time <診断で許可された値>
```

`ICAP_LAMPSTATE`が公開されない、またはSET拒否の場合はLED停止をハード側改造の課題として扱う。

`ICAP_EXPOSURETIME`が公開された場合は、値を変えたときの画像輝度だけでなく、飽和、暗部S/N、走査時間の変化も記録し、単なるデジタル輝度補正との違いを確認する。

## 5. CIで保証しないこと

以下は実機試験でのみ確認できる。

- fi-65Fの実Data Source名
- PaperStream TWAINの実Capability集合
- Capability値の単位・範囲
- Data Source固有のSET副作用
- LEDのソフトウェア制御可否
- 実際のnative transfer
- CISの積分時間・走査時間
- 実画像のS/N、ダイナミックレンジ、色再現
- ハード改造後の動作

## 6. 再確認トリガー

以下の変更時は実機確認を再実施する。

- PaperStream/WIA/TWAINドライバー更新
- TWAINDSM更新
- Python/pytwain更新
- fi-65FのUSB接続条件変更
- WIA/TWAIN Capability制御コード変更
- 画像保存方式変更
- LED/導光系のハード改造
