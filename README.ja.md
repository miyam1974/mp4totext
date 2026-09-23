# mp4totext

MP4ファイルを端末内で文字起こしするWindowsアプリケーションです。動画や音声は外部へ送信しません。初回利用時のみ、文字起こしモデルのダウンロードに通信を使用します。

[English](README.md) | [日本語](README.ja.md)

## 開発環境

- Windows 10/11 (64-bit)
- Python 3.12または3.13
- CPUによる文字起こし

Python 3.14は、音声・機械学習関連パッケージの対応が安定するまで対象外です。

## セットアップ

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[cli,gui,dev,build]"
```

## CLI

既定ではTXTを入力MP4と同じフォルダーへ出力します。JSON出力も選択できます。

```powershell
.\.venv\Scripts\mp4totext.exe .\meeting.mp4
.\.venv\Scripts\mp4totext.exe .\meeting.mp4 -f txt -f json --language ja
```

## Windowsアプリ

portable版を起動する場合:

```powershell
.\dist\mp4totext\mp4totext.exe
```

開発環境から起動する場合:

```powershell
.\.venv\Scripts\mp4totext-gui.exe
```

複数のMP4をまとめて画面へドロップし、出力形式と保存先を選択して文字起こしを開始します。ファイルは一覧の順に処理され、現在の対象ファイル名と処理状態が表示されます。

Windowsアプリの保存先は「動画と同じフォルダ」または「指定フォルダ」から選択できます。「指定フォルダ」を選んだ場合、初回起動時はWindowsの「ドキュメント」フォルダーが既定値です。選択または入力した保存先・モードはユーザー設定として保持され、次回起動時に復元されます。動画を追加する前でも「開く」でエクスプローラーを開けます(「指定フォルダ」選択時のみ)。

動画を追加したとき、選択中の全出力形式に対応する想定ファイル（例: `meeting.txt`と`meeting.json`）が保存先に存在すると、一覧へ「文字起こし済み」と表示します。保存先または出力形式を変更した場合も再判定します。

文字起こし中は、対象動画のファイルサイズ、予測処理時間、現在までの経過時間を表示します。成功した処理についてモデル名・動画ファイルサイズ・処理時間をユーザー設定へ記録し、同じモデルの直近履歴における処理速度の中央値から次回の予測時間を算出します。対象モデルの履歴がない場合は「履歴なし」と表示します。

動画一覧の各ファイル末尾にも、現在選択中のモデルに対応する予測時間を表示します。モデルを変更した場合や処理履歴が追加された場合は一覧を再計算します。ファイルサイズを取得できない場合は「算出不可」と表示します。

予測は動画ファイルサイズを基準にした概算です。動画の圧縮率、音声の長さ、無音部分、PC負荷などにより実際の処理時間と差が生じます。

一覧でファイルを選択し、現在処理中のファイルを除いて、待機・完了・失敗のいずれでも「削除」できます。「上へ」「下へ」は待機中のファイルのみ並べ替えできます。「フォルダを開く」は、選択中のファイルがあるフォルダーを、状態に関わらず開きます。文字起こし中も、現在処理中のファイルを除く待機中のファイルは編集できます。「終了」は処理していないときにアプリを閉じます。

一覧の各行には、元動画ファイルのサイズをMB単位で表示します。

文字起こし中でも動画のドロップや追加ができ、待機キューへ追加されて現在のバッチの後に処理されます。

## 文字起こしモデル

文字起こしには[`faster-whisper`](https://github.com/SYSTRAN/faster-whisper)を使用します。これはOpenAI WhisperモデルをCTranslate2形式へ変換し、CPUで効率よく実行する実装です。このアプリではCPUの`int8`演算を使用します。

モデルは[Hugging Face Hub](https://huggingface.co/Systran)で公開されているSystranのCTranslate2変換済みモデルから選択します。

| 画面上の名前 | ダウンロード元 | 用途 |
| --- | --- | --- |
| `tiny` | [`Systran/faster-whisper-tiny`](https://huggingface.co/Systran/faster-whisper-tiny) | 最も軽量・高速 |
| `base` | [`Systran/faster-whisper-base`](https://huggingface.co/Systran/faster-whisper-base) | 軽量 |
| `small` | [`Systran/faster-whisper-small`](https://huggingface.co/Systran/faster-whisper-small) | 既定値。速度と精度のバランスを優先 |
| `medium` | [`Systran/faster-whisper-medium`](https://huggingface.co/Systran/faster-whisper-medium) | 高精度だが処理時間とメモリ使用量が増加 |

初回利用時は選択したリポジトリから`model.bin`、設定、トークナイザー、語彙ファイルをダウンロードするため、インターネット接続が必要です。動画や音声、生成した文字起こしは送信しません。

ダウンロード中はモデル欄に取得状況と割合が表示されます。この間も「モデル取得をキャンセル」を押して中止できます。取得が完了して文字起こしへ移る時点で、モデル欄はダウンロード済みのモデル名とファイルサイズへ更新されます。

モデルは`%LOCALAPPDATA%\mp4totext\Cache\models`へ保存され、同じWindowsユーザーで同じモデルを選んだ次回起動時は通信せず再利用されます。モデルを変更した場合は、そのモデルを別途ダウンロードします。

画面下部には、プルダウンで選択しているモデルのダウンロード状態と、ダウンロード済みの場合はディスク使用量を常時表示します。「選択モデルを削除」は現在選択中のモデルだけを削除します。削除後にそのモデルで文字起こしを開始すると、モデルを改めてダウンロードします。

「アプリ情報を削除」はダウンロード済みモデルを含む`%LOCALAPPDATA%\mp4totext\Cache`内のアプリ専用キャッシュを削除します。入力MP4と生成したTXT/JSONは削除しません。

画面最下部の「デバッグ」には、文字起こしやモデル操作で発生したエラーの詳細を表示します。表示欄は2行分の高さで縦にスクロールでき、文字列を選択してキーボード(Ctrl+C)でコピーできます。

### モデルとソフトウェアのライセンス

ダウンロード対象の次のCTranslate2変換済みモデルは、各Hugging Faceモデルカードで**MIT License**と表示されています。

- [`Systran/faster-whisper-tiny`](https://huggingface.co/Systran/faster-whisper-tiny)
- [`Systran/faster-whisper-base`](https://huggingface.co/Systran/faster-whisper-base)
- [`Systran/faster-whisper-small`](https://huggingface.co/Systran/faster-whisper-small)
- [`Systran/faster-whisper-medium`](https://huggingface.co/Systran/faster-whisper-medium)

文字起こし実装の[`SYSTRAN/faster-whisper`](https://github.com/SYSTRAN/faster-whisper)も[MIT License](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE)です。モデルやアプリを再配布する場合は、リンク先の最新のライセンス本文と著作権表示を確認し、該当するライセンス条件に従ってください。

### 社内ネットワークでの証明書エラー

モデルのダウンロードではWindowsの証明書ストアを使用します。HTTPSを検査する社内プロキシ環境では、社内ルート証明書をWindowsの「信頼されたルート証明機関」に登録してください。

証明書をWindowsへ登録できない場合は、PEM形式のCA証明書を用意し、起動前に環境変数を設定します。

```powershell
$env:SSL_CERT_FILE = "C:\path\to\company-ca.pem"
.\dist\mp4totext\mp4totext.exe
```

## テストとビルド

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src tests
.\.venv\Scripts\pyinstaller.exe --noconfirm .\packaging\mp4totext.spec
```

portable版は`dist\mp4totext`に生成されます。このフォルダー全体を配布してください。

## GitHub Actionsでの自動ビルド

GitHubへ`main`または`master`ブランチをpushすると、GitHub ActionsがWindows上でexeをビルドします。`v1.0.0`のようなタグをpushした場合もビルドされます。手動で実行する場合は、リポジトリの`Actions`タブから`Build Windows executable`を選び、`Run workflow`を実行してください。

ビルド完了後、Workflowの実行結果にある`Artifacts`から`mp4totext-windows`をダウンロードできます。成果物には`dist\mp4totext`フォルダーが含まれます。

## ライセンス

このプロジェクトは[MITライセンス](LICENSE)のもとで公開しています。

`faster-whisper`と同梱のWhisperモデルもMIT Licenseです。詳細と再配布時の注意点は上記の[モデルとソフトウェアのライセンス](#モデルとソフトウェアのライセンス)を参照してください。
