"""Static translation table for the GUI (Japanese / English)."""

from enum import StrEnum

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QTranslator


class Language(StrEnum):
    JA = "ja"
    EN = "en"


_STRINGS: dict[str, dict[Language, str]] = {
    "error_details_hint": {
        Language.JA: "詳細はデバッグ欄を確認してください。",
        Language.EN: "See the Debug panel for details.",
    },
    "window_title": {
        Language.JA: "MP4 to Text",
        Language.EN: "MP4 to Text",
    },
    "subtitle": {
        Language.JA: "動画を外部へ送信せず、このPCで文字起こしします",
        Language.EN: "Transcribes video on this PC without sending it anywhere",
    },
    "label_video": {Language.JA: "動画", Language.EN: "Video"},
    "label_destination": {Language.JA: "保存先", Language.EN: "Destination"},
    "label_output_format": {Language.JA: "出力形式", Language.EN: "Output"},
    "label_model": {Language.JA: "モデル", Language.EN: "Model"},
    "label_processing": {Language.JA: "処理中", Language.EN: "Processing"},
    "label_state": {Language.JA: "状態", Language.EN: "State"},
    "label_debug": {Language.JA: "デバッグ", Language.EN: "Debug"},
    "add_files": {Language.JA: "MP4を追加", Language.EN: "Add MP4"},
    "remove": {Language.JA: "削除", Language.EN: "Remove"},
    "move_up": {Language.JA: "上へ", Language.EN: "Up"},
    "move_down": {Language.JA: "下へ", Language.EN: "Down"},
    "open_folder": {Language.JA: "フォルダを開く", Language.EN: "Open folder"},
    "same_folder": {Language.JA: "動画と同じフォルダ", Language.EN: "Same folder as video"},
    "custom_folder": {Language.JA: "指定フォルダ", Language.EN: "Specified folder"},
    "browse": {Language.JA: "参照", Language.EN: "Browse"},
    "open": {Language.JA: "開く", Language.EN: "Open"},
    "delete_selected_model": {
        Language.JA: "選択モデルを削除",
        Language.EN: "Delete selected model",
    },
    "delete_app_data": {Language.JA: "アプリ情報を削除", Language.EN: "Delete app data"},
    "cancel": {Language.JA: "キャンセル", Language.EN: "Cancel"},
    "cancel_model_download": {
        Language.JA: "モデル取得をキャンセル",
        Language.EN: "Cancel model download",
    },
    "exit": {Language.JA: "終了", Language.EN: "Exit"},
    "start": {Language.JA: "文字起こしを開始", Language.EN: "Start transcription"},
    "select_mp4_prompt": {
        Language.JA: "MP4ファイルを選択してください",
        Language.EN: "Select an MP4 file",
    },
    "none": {Language.JA: "なし", Language.EN: "None"},
    "debug_placeholder": {
        Language.JA: "エラーの詳細がここに表示されます",
        Language.EN: "Error details will appear here",
    },
    "drop_hint": {
        Language.JA: "複数のMP4ファイルをここにドロップ（または右のボタンで指定）",
        Language.EN: "Drop multiple MP4 files here (or use the button on the right)",
    },
    "select_mp4_dialog_title": {Language.JA: "MP4を選択", Language.EN: "Select MP4"},
    "select_destination_dialog_title": {
        Language.JA: "保存先を選択",
        Language.EN: "Select destination",
    },
    "folder_title": {Language.JA: "フォルダ", Language.EN: "Folder"},
    "destination_title": {Language.JA: "保存先", Language.EN: "Destination"},
    "folder_not_found": {
        Language.JA: "フォルダーが見つかりません。\n{path}",
        Language.EN: "Folder not found.\n{path}",
    },
    "folder_open_failed": {
        Language.JA: "フォルダを開けませんでした",
        Language.EN: "Could not open the folder",
    },
    "destination_open_failed": {
        Language.JA: "保存先を開けませんでした",
        Language.EN: "Could not open the destination",
    },
    "output_format_title": {Language.JA: "出力形式", Language.EN: "Output format"},
    "output_format_required": {
        Language.JA: "出力形式を1つ以上選択してください。",
        Language.EN: "Select at least one output format.",
    },
    "overwrite_confirm_title": {Language.JA: "上書き確認", Language.EN: "Confirm overwrite"},
    "overwrite_confirm_message": {
        Language.JA: "既存の出力ファイルを上書きしますか？",
        Language.EN: "Overwrite the existing output files?",
    },
    "files_selected": {
        Language.JA: "{count} ファイルを選択中",
        Language.EN: "{count} file(s) selected",
    },
    "stage_preparing": {Language.JA: "MP4を確認しています", Language.EN: "Checking the MP4 file"},
    "stage_downloading_model": {
        Language.JA: "文字起こしモデルを準備しています",
        Language.EN: "Preparing the transcription model",
    },
    "stage_transcribing": {Language.JA: "文字起こし中", Language.EN: "Transcribing"},
    "stage_saving": {Language.JA: "結果を保存しています", Language.EN: "Saving results"},
    "stage_completed": {Language.JA: "完了しました", Language.EN: "Completed"},
    "preparing": {Language.JA: "準備中", Language.EN: "Preparing"},
    "downloading": {
        Language.JA: "ダウンロード中 ({percent})",
        Language.EN: "Downloading ({percent})",
    },
    "downloaded": {Language.JA: "ダウンロード済み ({size})", Language.EN: "Downloaded ({size})"},
    "not_downloaded": {Language.JA: "未ダウンロード", Language.EN: "Not downloaded"},
    "status_check_error": {Language.JA: "状態確認エラー", Language.EN: "Status check failed"},
    "batch_completed_status": {
        Language.JA: "完了: {completed}件 / 失敗: {failed}件",
        Language.EN: "Done: {completed} / Failed: {failed}",
    },
    "batch_completed_title": {
        Language.JA: "文字起こし完了",
        Language.EN: "Transcription complete",
    },
    "batch_completed_message": {
        Language.JA: "{completed}件を文字起こししました。失敗: {failed}件",
        Language.EN: "Transcribed {completed} file(s). Failed: {failed}",
    },
    "cancelled_status": {Language.JA: "キャンセルしました", Language.EN: "Cancelled"},
    "cancelling_status": {Language.JA: "キャンセルしています", Language.EN: "Cancelling..."},
    "history_none": {Language.JA: "履歴なし", Language.EN: "No history"},
    "size_unavailable": {Language.JA: "算出不可", Language.EN: "Unavailable"},
    "model_delete_title": {Language.JA: "モデル削除", Language.EN: "Delete model"},
    "model_delete_confirm": {
        Language.JA: "ダウンロード済みの {model} モデルを削除しますか？",
        Language.EN: "Delete the downloaded {model} model?",
    },
    "model_delete_error_title": {
        Language.JA: "モデル削除エラー",
        Language.EN: "Model deletion error",
    },
    "model_delete_failed_debug": {
        Language.JA: "モデル削除に失敗しました",
        Language.EN: "Failed to delete the model",
    },
    "app_data_delete_title": {Language.JA: "アプリ情報の削除", Language.EN: "Delete app data"},
    "app_data_delete_confirm": {
        Language.JA: "ダウンロード済みモデルを含む、このアプリのキャッシュをすべて削除しますか？",
        Language.EN: "Delete all of this app's cache, including downloaded models?",
    },
    "app_data_delete_error_title": {
        Language.JA: "アプリ情報削除エラー",
        Language.EN: "App data deletion error",
    },
    "app_data_delete_failed_debug": {
        Language.JA: "アプリ情報削除に失敗しました",
        Language.EN: "Failed to delete app data",
    },
    "model_status_failed_debug": {
        Language.JA: "モデル状態の確認に失敗しました",
        Language.EN: "Failed to check model status",
    },
    "processing_in_progress_title": {Language.JA: "処理中", Language.EN: "Processing"},
    "processing_in_progress_message": {
        Language.JA: "文字起こしをキャンセルしてから終了してください。",
        Language.EN: "Cancel the transcription before exiting.",
    },
    "queue_pending": {Language.JA: "待機", Language.EN: "Pending"},
    "queue_active": {Language.JA: "処理中", Language.EN: "Active"},
    "queue_completed": {Language.JA: "完了", Language.EN: "Completed"},
    "queue_failed": {Language.JA: "失敗", Language.EN: "Failed"},
    "queue_transcribed": {Language.JA: "文字起こし済み", Language.EN: "Transcribed"},
    "queue_item_transcribed": {
        Language.JA: "[{state} / {transcribed}] {name} ({size}) / 予測: {prediction}",
        Language.EN: "[{state} / {transcribed}] {name} ({size}) / Est: {prediction}",
    },
    "queue_item": {
        Language.JA: "[{state}] {name} ({size}) / 予測: {prediction}",
        Language.EN: "[{state}] {name} ({size}) / Est: {prediction}",
    },
    "active_file_progress": {
        Language.JA: "{name} ({index}/{total})",
        Language.EN: "{name} ({index}/{total})",
    },
    "timing_text": {
        Language.JA: "サイズ: {size} / 予測: {estimate} / 経過: {elapsed}",
        Language.EN: "Size: {size} / Est: {estimate} / Elapsed: {elapsed}",
    },
    "timing_placeholder": {
        Language.JA: "サイズ: - / 予測: - / 経過: -",
        Language.EN: "Size: - / Est: - / Elapsed: -",
    },
    "model_description_tiny": {Language.JA: "最も軽量・高速", Language.EN: "Lightest and fastest"},
    "model_description_base": {Language.JA: "軽量", Language.EN: "Lightweight"},
    "model_description_small": {
        Language.JA: "既定値。速度と精度のバランスを優先",
        Language.EN: "Default. Balances speed and accuracy",
    },
    "model_description_medium": {
        Language.JA: "高精度だが処理時間とメモリ使用量が増加",
        Language.EN: "More accurate, but slower and uses more memory",
    },
}


class Translator:
    def __init__(self, language: Language = Language.JA) -> None:
        self.language = language

    def t(self, key: str, **kwargs: object) -> str:
        return _STRINGS[key][self.language].format(**kwargs)


def set_qt_language(language: Language) -> None:
    """Translate Qt's standard widgets using the application's chosen language."""
    application = QCoreApplication.instance()
    if application is None:
        return
    translator = application.findChild(QTranslator, "mp4totext_qt_translator")
    if translator is None:
        translator = QTranslator(application)
        translator.setObjectName("mp4totext_qt_translator")
    application.removeTranslator(translator)
    if language is Language.JA and translator.load(
        "qtbase_ja", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    ):
        application.installTranslator(translator)
