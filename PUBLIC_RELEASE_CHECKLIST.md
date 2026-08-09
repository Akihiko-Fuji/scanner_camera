# Public Release Checklist

この文書は`scanner_camera`を非公開実験リポジトリから公開可能な状態へ移すための判定記録です。

チェックが完了するまでは、CI成功だけを根拠に公開可能とは扱いません。

## A. Source / CI

- [ ] 公開候補HEADを固定した
- [ ] Python 3.8.10 x86 CI: completed / success
- [ ] Python 3.11 x64 CI: completed / success
- [ ] Python 3.12 x64 CI: completed / success
- [ ] x86 laneが`requirements-dev-win8-x86.txt`を使用した
- [ ] `pip check`成功
- [ ] `compileall`成功
- [ ] pytest成功
- [ ] 既知のP1/P2レビュー指摘が未解決で残っていない

## B. Windows 8 32-bit runtime

- [ ] Windows 8 32-bit実機でPython 3.8.10 x86を確認
- [ ] `requirements-win8-x86.txt`を新規環境へ導入できる
- [ ] `pip check`成功
- [ ] `import win32com.client, PIL, twain`成功
- [ ] fi-65F Driverのバージョンを記録

## C. WIA実機

- [ ] `scanner_capture.py --list-devices`でfi-65Fを確認
- [ ] read-only `--diagnose`成功
- [ ] 診断結果で`probe_writes=false`を確認
- [ ] 明示`--probe-writes`の実施可否を判断
- [ ] 600 dpi color取得成功
- [ ] grayscale取得成功
- [ ] bw取得成功
- [ ] 連番が既存画像を上書きしない
- [ ] 失敗時に壊れた完成JPEGが残らない
- [ ] 連続3回以上の取得成功
- [ ] `Win32 exception occurred releasing IUnknown`が再発しない

## D. TWAIN実機

- [ ] `twain_capture.py --list-devices`でfi-65F Data Sourceを確認
- [ ] 実行中Pythonが32-bitであることを診断へ記録
- [ ] 使用DSMを記録
- [ ] read-only `--diagnose`成功
- [ ] `CAP_SUPPORTEDCAPS`取得結果を保存
- [ ] `ICAP_XRESOLUTION` / `ICAP_YRESOLUTION`を確認
- [ ] `ICAP_BRIGHTNESS` / `ICAP_CONTRAST`を確認
- [ ] `ICAP_AUTOBRIGHT`を確認
- [ ] `ICAP_EXPOSURETIME`を確認
- [ ] `ICAP_GAMMA`を確認
- [ ] `ICAP_LAMPSTATE`を確認
- [ ] `ICAP_LIGHTSOURCE` / `ICAP_LIGHTPATH`を確認
- [ ] `DAT_IMAGELAYOUT`を確認
- [ ] 必要に応じて明示`--probe-writes`を実施
- [ ] 600 dpi color native transfer成功
- [ ] JPEG DPI metadataが`DAT_IMAGEINFO`と整合
- [ ] Sourceをclose後、次回実行で正常に再openできる
- [ ] 連続3回以上の取得成功

## E. Scanner camera / hard modification

- [ ] LED停止/遮光方式を確定
- [ ] ハード改造後もWIA/TWAINで取得可能
- [ ] 内蔵LED光の混入が許容範囲以下
- [ ] 外部レンズ投影像の結像を確認
- [ ] 焦点合わせ可能範囲を確認
- [ ] 外部像でcolor / grayscaleの成立性を確認
- [ ] `brightness`と物理露出を混同しない説明をREADMEへ維持
- [ ] `ICAP_EXPOSURETIME`が有効なら実際の効果を測定

## F. Data / privacy

- [ ] `jpeg/`が`.gitignore`対象
- [ ] `diagnostics/`が`.gitignore`対象
- [ ] commit履歴に公開したくない撮影画像がない
- [ ] commit履歴にDevice ID等の不要な実機情報がない
- [ ] 公開用の診断例を載せる場合は識別情報を確認/必要に応じて除去

## G. Documentation

- [ ] READMEのWindows 8 x86手順を実機結果で再確認
- [ ] READMEのDSM説明を実機結果で再確認
- [ ] READMEのCapability一覧を実機診断結果へ合わせる
- [ ] TESTING.mdを最終実機手順へ合わせる
- [ ] 既知の制限を明記
- [ ] 公開時のバージョン番号を確定

## H. License / distribution

- [ ] このリポジトリ自身のLICENSEを決定
- [ ] `pywin32`のライセンス条件を確認
- [ ] `Pillow`のライセンス条件を確認
- [ ] `pytwain==2.3.0`のライセンス条件を確認
- [ ] source公開のみか、バイナリ/installerも配布するか決定
- [ ] 配布形態と依存ライセンスの整合を確認
- [ ] 必要なcopyright / noticeを追加

## I. Release decision

- [ ] 上記未完了項目に公開を阻害するものがない
- [ ] 実機試験結果をcommit/issue/文書のいずれかに記録
- [ ] Release Candidateから公開版へ移行する判断を記録
- [ ] 公開前に最終HEADのCIを再確認
