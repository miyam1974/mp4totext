# mp4totext

A Windows application that transcribes MP4 files on-device. Video and audio are never sent anywhere; an internet connection is only needed once, to download the transcription model.

[English](README.md) | [日本語](README.ja.md)

## Development environment

- Windows 10/11 (64-bit)
- Python 3.12 or 3.13
- CPU-based transcription

Python 3.14 is not yet supported, until audio/ML-related packages have stabilized on it.

## Setup

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[cli,gui,dev,build]"
```

## CLI

By default, a TXT file is written to the same folder as the input MP4. JSON output can also be selected.

```powershell
.\.venv\Scripts\mp4totext.exe .\meeting.mp4
.\.venv\Scripts\mp4totext.exe .\meeting.mp4 -f txt -f json --language ja
```

## Windows app

To launch the portable build:

```powershell
.\dist\mp4totext\mp4totext.exe
```

To launch from the development environment:

```powershell
.\.venv\Scripts\mp4totext-gui.exe
```

Drop multiple MP4 files onto the window, choose the output format(s) and destination folder, and start transcription. Files are processed in list order, and the current file name and status are shown.

You can choose the destination mode: "Same folder as the video" or "Specified folder." When "Specified folder" is selected, the default on first launch is the user's "Documents" folder. The chosen mode and destination are saved as user settings and restored on the next launch. You can open the destination in Explorer with "Open" even before adding any video (only while "Specified folder" is selected).

When a video is added, if the expected output files for all currently selected formats (for example `meeting.txt` and `meeting.json`) already exist in the destination, the list marks it as "Transcribed." This is re-evaluated whenever the destination or output formats change.

While transcribing, the app shows the target video's file size, an estimated processing time, and the elapsed time so far. On success, the model name, video file size, and processing time are recorded in user settings, and the next estimate is derived from the median processing speed of recent history for that model. If there is no history for the selected model, it shows "No history."

Each file in the video list also shows an estimated time for the currently selected model. The list is recalculated whenever the model changes or new processing history is recorded. If a file's size cannot be determined, it shows "Cannot estimate."

Estimates are rough approximations based on video file size. Actual processing time can differ due to video compression ratio, audio length, silence, and system load.

You can select a file in the list and use "Remove" regardless of its status (pending, completed, or failed), except the one currently being processed. "Move up" and "Move down" reorder pending files only. "Open folder" opens the folder containing the selected file, for any file regardless of its status. While transcription is running, pending files other than the one currently being processed remain editable. "Exit" closes the app only when nothing is being processed.

Each entry in the list shows the source file's size in MB.

You can drop or add more MP4 files while transcription is running; they are appended to the pending queue and processed after the current batch.

## Transcription model

Transcription uses [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper), which converts OpenAI Whisper models to the CTranslate2 format for efficient CPU execution. This app uses `int8` CPU computation.

Models are chosen from Systran's CTranslate2-converted models published on the [Hugging Face Hub](https://huggingface.co/Systran).

| Name in the app | Source | Notes |
| --- | --- | --- |
| `tiny` | [`Systran/faster-whisper-tiny`](https://huggingface.co/Systran/faster-whisper-tiny) | Lightest and fastest |
| `base` | [`Systran/faster-whisper-base`](https://huggingface.co/Systran/faster-whisper-base) | Lightweight |
| `small` | [`Systran/faster-whisper-small`](https://huggingface.co/Systran/faster-whisper-small) | Default. Favors a balance of speed and accuracy |
| `medium` | [`Systran/faster-whisper-medium`](https://huggingface.co/Systran/faster-whisper-medium) | More accurate, but slower and uses more memory |

On first use, an internet connection is required to download `model.bin`, its configuration, tokenizer, and vocabulary files from the selected repository. Video, audio, and generated transcripts are never sent anywhere.

While downloading, the model field shows progress and a percentage. You can cancel with "Cancel model download" during this time. Once the download finishes and transcription begins, the model field updates to show the downloaded model's name and file size.

Models are stored under `%LOCALAPPDATA%\mp4totext\Cache\models`. If the same Windows user selects the same model on a later launch, it is reused without any network access. Selecting a different model downloads it separately.

The bottom of the window always shows the download status of the model currently selected in the dropdown, and its disk usage once downloaded. "Delete selected model" removes only the currently selected model; starting a transcription with that model afterward downloads it again.

"Delete app data" removes the app's dedicated cache under `%LOCALAPPDATA%\mp4totext\Cache`, including downloaded models. It does not delete the input MP4 files or the generated TXT/JSON files.

The "Debug" panel at the bottom of the window shows details of any errors from transcription or model operations. It is about two lines tall and scrolls vertically; its text can be selected and copied with the keyboard (Ctrl+C).

### Model and software licenses

The following CTranslate2-converted models are listed as **MIT License** on their respective Hugging Face model cards:

- [`Systran/faster-whisper-tiny`](https://huggingface.co/Systran/faster-whisper-tiny)
- [`Systran/faster-whisper-base`](https://huggingface.co/Systran/faster-whisper-base)
- [`Systran/faster-whisper-small`](https://huggingface.co/Systran/faster-whisper-small)
- [`Systran/faster-whisper-medium`](https://huggingface.co/Systran/faster-whisper-medium)

The transcription implementation [`SYSTRAN/faster-whisper`](https://github.com/SYSTRAN/faster-whisper) is also [MIT-licensed](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE). If you redistribute the models or this app, check the latest license text and copyright notices at the linked sources and comply with the applicable terms.

## Certificate errors on corporate networks

Model downloads use the Windows certificate store. On corporate networks that inspect HTTPS traffic, register your organization's root certificate in Windows' "Trusted Root Certification Authorities."

If you can't register the certificate in Windows, prepare a PEM-format CA certificate and set an environment variable before launching the app:

```powershell
$env:SSL_CERT_FILE = "C:\path\to\company-ca.pem"
.\dist\mp4totext\mp4totext.exe
```

## Tests and build

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src tests
.\.venv\Scripts\pyinstaller.exe --noconfirm .\packaging\mp4totext.spec
```

The portable build is generated at `dist\mp4totext`. Distribute this entire folder.

## Automatic builds with GitHub Actions

Pushing to the `main` or `master` branch starts a Windows build in GitHub Actions. Pushing a tag such as `v1.0.0` also starts a build. To run it manually, open the repository's `Actions` tab, select `Build Windows executable`, and choose `Run workflow`.

After the workflow completes, download `mp4totext-windows` from `Artifacts` on the workflow run page. The artifact contains the `dist\mp4totext` folder.

## License

This project is released under the [MIT License](LICENSE).

`faster-whisper` and the bundled Whisper models are also MIT-licensed; see [Model and software licenses](#model-and-software-licenses) above for details and redistribution notes.

