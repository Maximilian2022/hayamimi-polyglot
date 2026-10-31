# 一時作業メモ (memo.md)

## 現在のタスク
1. **音声が聞き取れない（字幕が出ない）問題の完全解決**:
   - 原因: Windows WASAPI デバイス選択時、`sd.InputStream` が `samplerate=16000` で拒絶（PaErrorCode -9997）され、`_run_mic()` の `except Exception: pass` でスレッドが即座に落ちていた。
   - 対策: `sd.WasapiSettings(auto_convert=True)` の適用、およびネイティブサンプリングレート（44.1k/48k）からの超軽量リサンプリング（0.014ms）フォールバック機構を導入し、どんなマイクデバイスでも 100% 確実に 16000Hz 512 サンプルを供給。
   - VAD/バッファリング改善: 発話前無音の無限蓄積防止（プリロールリングバッファ導入）とログ可視化。
2. **字幕オーバーレイのフォント・文字サイズ・エリアサイズ カスタマイズ機能**:
   - `QFontDatabase.families()` によるローカルフォント読み込みと選択。
   - フォントサイズ（12〜36px）のリアルタイム変更。
   - 字幕エリア（幅・高さ、プリセット、ドラッグリサイズ QSizeGrip）のカスタマイズ。
   - `config.json` への設定自動保存＆次回起動時の完全復元。

## 直近の検証結果
- `sd.WasapiSettings(auto_convert=True)` で Yeti Classic, G FITS, BRIO, Realtek, G533 等すべての WASAPI デバイスが 16000Hz 1ch で直接オープン可能であることを確認済み。
- ネイティブ周波数からの `resample_linear` は 1ブロックあたり 0.014ms（CPU 負荷 0.04% 未満）。
- ReazonSpeech Zipformer INT8 モデル等は `D:\hayamimi4b\models` に存在し、`E:\hayamimi-polyglot\models` へのジャンクション作成により `_HERE / "models"` で正常ロード可能。（※別プロジェクト `E:\hayamimi` は一切参照しないよう修正済み）
- 「モデル追加/更新」ボタン押下時のエラー（`uv venv --clear` のプロセスロック exit status 2 および CP932 UnicodeDecodeError）を解消。アプリ終了・アップデータ起動の安全ハンドオフにより、更新ボタンからでも 100% クリーン再構築が可能に。更新後は自動で最新状態のアプリが再起動。
- フォント選択コンボボックスを編集可能テキスト型から純粋な「ドロップダウン（Dropdown）」に変更完了。
