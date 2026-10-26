"""Regression tests for Windows console stream lifetime."""
import io
import logging
from types import SimpleNamespace
from app import main


def test_pythonw_streams_remain_open_for_logging(monkeypatch):
    streams = SimpleNamespace(platform='win32', stdout=None, stderr=None)
    monkeypatch.setattr(main, 'sys', streams)
    main._configure_standard_streams()
    handler = main._create_stream_handler()
    try:
        handler.emit(logging.LogRecord('offline', logging.INFO, '', 1, 'local check', (), None))
        handler.flush()
        assert handler.stream is streams.stdout
        assert not streams.stdout.closed
        assert not streams.stderr.closed
        streams.stdout.write('still open')
    finally:
        handler.close()
        streams.stdout.close()
        streams.stderr.close()


def test_windows_utf8_reuses_the_original_buffer(monkeypatch):
    output = io.BytesIO()
    errors = io.BytesIO()
    streams = SimpleNamespace(platform='win32', stdout=io.TextIOWrapper(output, encoding='cp932'), stderr=io.TextIOWrapper(errors, encoding='cp932'))
    monkeypatch.setattr(main, 'sys', streams)
    monkeypatch.setattr(main, '_is_testing', False)
    main._configure_standard_streams()
    handler = main._create_stream_handler()
    try:
        handler.emit(logging.LogRecord('offline', logging.INFO, '', 1, '\u65e5\u672c\u8a9e', (), None))
        handler.flush()
        assert handler.stream is streams.stdout
        assert '\u65e5\u672c\u8a9e' in output.getvalue().decode('utf-8')
        assert not output.closed
    finally:
        handler.close()
        streams.stdout.close()
        streams.stderr.close()
