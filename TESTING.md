# テスト方針

本プロジェクトは64-bit Windowsを実行環境とし、WIAとTWAINの2経路を持つ。通常のCIではfi-65F実機を接続できないため、テストを「自動単体テスト」と「実機確認」に分ける。

## 自動単体テスト

### 共通

- `config.ini`とCLIの優先順位
- `DSC_####.jpeg`の採番と排他予約
- 失敗時の空予約ファイル削除
- JPEG変換
- strict／non-strict時の制御

### WIA

COM/WIAオブジェクトをテストダブルへ置き換え、以下を検証する。

- WIAプロパティ制約の解釈
- 診断ステータスの判定
- no-change write/read-back probe
- カラー／グレースケール／二値JPEG
- 診断・通常取り込みのCLI制御フロー

### TWAIN

TWAIN Data Sourceをテストダブルへ置き換え、実機やDSMを必要としない範囲を検証する。

- pytwain Capability戻り値のONEVALUE/RANGE/ENUMERATION相当の正規化
- `CAP_SUPPORTEDCAPS`からのCapability列挙
- `GET` / `GETCURRENT` / `GETDEFAULT`結果の診断化
- `MSG_QUERYSUPPORT`取得失敗時の安全なフォールバック
- scanner_camera対象Capabilityのno-change SET/read-back probe
- 非対象Capabilityを一律SETしないこと
- Source名の部分一致選択と曖昧一致拒否
- `ICAP_PIXELTYPE`、DPI、brightness等のSET
- `DAT_IMAGELAYOUT`のピクセル→インチ変換
- native transfer画像のJPEG保存
- `ICAP_EXPOSURETIME`、`ICAP_LAMPSTATE`等を診断対象として保持すること

実行方法：

```bat
python -m pip install -r requirements-dev.txt
python -m pytest
```

カバレッジを確認する場合：

```bat
python -m pytest --cov=scanner_capture --cov=twain_capture --cov-report=term-missing
```

GitHub Actionsでは`actions/setup-python`で選択したPythonを確実に使うため、Windowsの`py`ランチャーではなく`python -m ...`で実行する。

## 実機確認: WIA

fi-65Fを接続した64-bit Windowsで確認する。

1. `py scanner_capture.py --list-devices`
2. `py scanner_capture.py --device fi-65F --diagnose`
3. brightness、contrast、解像度の公開範囲を確認
4. brightness最小・中央・最大で各1枚取り込み
5. `./jpeg/DSC_####.jpeg`の生成、画像差、スキャン完了を確認

2026-08-07時点の実機確認では、Python 3.9.13 64-bitからfi-65FをWIA認識し、75～600 dpi、brightness/contrast -128～127の公開とSET/read-backを確認済み。

## 実機確認: TWAIN

TWAIN版は次の順序で確認する。最初の診断ではハード改造やLED停止を行わない。

1. 64-bit Python確認

```bat
py -c "import struct; print(struct.calcsize('P') * 8)"
```

2. TWAIN Source列挙

```bat
py twain_capture.py --list-devices
```

3. write probeなしで初回診断

```bat
py twain_capture.py --device fi-65F --diagnose --no-probe-writes
```

4. JSON/TXTで以下を重点確認

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

5. Sourceが安定して応答したらno-change write probeを実施

```bat
py twain_capture.py --device fi-65F --diagnose
```

6. WIAと同条件の基本取り込み

```bat
py twain_capture.py --device fi-65F --dpi 600 --mode color --brightness -128 --contrast 0
```

7. TWAIN固有CapabilityがSET可能な場合のみ個別試験

```bat
py twain_capture.py --device fi-65F --lamp-state off
py twain_capture.py --device fi-65F --autobright off --exposure-time <診断で許可された値>
```

`ICAP_LAMPSTATE`が公開されない、またはSET拒否の場合はLED停止をハード側改造の課題として扱う。

## 再確認トリガー

以下の変更時は実機確認を再実施する。

- PaperStream/WIA/TWAINドライバー更新
- TWAINDSM更新
- Python/pytwain更新
- fi-65FのUSB接続条件変更
- WIA/TWAIN Capability制御コード変更
- LED/導光系のハード改造
