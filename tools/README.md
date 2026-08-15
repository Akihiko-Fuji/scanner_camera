# TWAIN DSM probe tools

`twain_dsm_probe.py`は、32-bit Windowsで`twain_32.dll`の`DAT_PARENT / MSG_OPENDSM`が失敗する場合に、`parent_window=0`と有効なhidden Tk window handleの差だけを切り分ける実機診断です。

このツールはDSMを開いてSource名を列挙するだけで、Data Sourceを開かず、CapabilityのSETや画像取得は行いません。

Windows 8 x86最終環境相当では、固定したPython 3.8.10 x86を明示して実行します。

```bat
py -3.8-32 tools\twain_dsm_probe.py
```

比較のため、現在の`twain_capture.py`と同じ`HWND=0`でも実行できます。

```bat
py -3.8-32 tools\twain_dsm_probe.py --zero-parent
```

詳細例外が必要なら`--verbose`を付けます。

```bat
py -3.8-32 tools\twain_dsm_probe.py --verbose
```

判定：

- hidden Tk parentのみ成功する場合: `twain_capture.py`のSourceManager生成を有効なparent HWND保持方式へ変更する。
- 両方失敗する場合: parent HWNDは主因ではないため、DSM / application identity / pytwain境界の調査を継続する。
- 両方成功する場合: 元の失敗条件と環境差を再確認する。
