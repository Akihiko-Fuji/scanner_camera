# テスト方針

本プロジェクトは64-bit WindowsとWIAを実行環境とする。一方、通常のCIではfi-65F実機を接続できないため、テストを次の2層に分ける。

## 自動単体テスト

COM/WIAオブジェクトをテストダブルへ置き換え、以下を検証する。

- `config.ini`とCLIの優先順位
- WIAプロパティ制約の解釈
- 診断ステータスの判定
- strict／non-strict時の設定処理
- `DSC_####.jpeg`の採番と排他予約
- 失敗時の空予約ファイル削除
- JPEG変換とカラーモード
- 診断・通常取り込みのCLI制御フロー

実行方法：

```bat
py -m pip install -r requirements-dev.txt
py -m pytest
```

カバレッジを確認する場合：

```bat
py -m pytest --cov=scanner_capture --cov-report=term-missing
```

## 実機確認

以下は自動テストでは保証できないため、fi-65Fを接続した64-bit Windowsで確認する。

1. `py scanner_capture.py --list-devices`
2. `py scanner_capture.py --device fi-65F --diagnose`
3. 診断結果でbrightness、contrast、解像度の公開範囲を確認
4. 最小・中央・最大のbrightnessで各1枚取り込み
5. `./jpeg/DSC_####.jpeg`の生成、画像差、スキャン完了を確認

実機確認はドライバー更新時、fi-65Fの接続方式変更時、WIA/TWAIN制御変更時に再実施する。
