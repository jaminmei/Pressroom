from __future__ import annotations

import argparse
import sys
from typing import Any, Callable, Sequence

from pressroom_cli import __version__
from pressroom_cli.domain_commands import (
    DOMAIN_ROOTS,
    dispatch_domain,
    register_domain_commands,
)
from pressroom_cli.errors import USAGE, CliError
from pressroom_cli.io_utils import write_binary_atomic
from pressroom_cli.output import emit_human, emit_json, error_envelope, success_envelope
from pressroom_cli.runtime import CommandResult, Runtime
from pressroom_cli.transport import ApiClient


def _leaf(
    parent: argparse._SubParsersAction[argparse.ArgumentParser], name: str, help_text: str
) -> argparse.ArgumentParser:
    return parent.add_parser(name, help=help_text, description=help_text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr",
        description="PressRoom Agent business-tool CLI",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--json", action="store_true", help="emit one stable JSON envelope")
    parser.add_argument("--timeout", type=float, default=30.0, help="request timeout in seconds")
    commands = parser.add_subparsers(dest="root_command", required=True)

    file_command = _leaf(commands, "file", "manage durable workspace files")
    file_commands = file_command.add_subparsers(dest="file_command", required=True)
    upload = _leaf(file_commands, "upload", "upload an authorized Agent Session file")
    upload.add_argument("--file", required=True, dest="file_path")
    file_list = _leaf(file_commands, "list", "list workspace files")
    file_list.add_argument("--page", type=int, default=1)
    file_list.add_argument("--limit", type=int, default=50)
    file_list.add_argument("--query")
    file_get = _leaf(file_commands, "get", "get file metadata")
    file_get.add_argument("file_id")
    download = _leaf(file_commands, "download", "download file content")
    download.add_argument("file_id")
    download.add_argument("--output", required=True)
    download.add_argument("--force", action="store_true")
    file_delete = _leaf(file_commands, "delete", "delete an unreferenced file")
    file_delete.add_argument("file_id")
    file_delete.add_argument("--yes", action="store_true")

    register_domain_commands(commands)
    return parser


def _extract_global_options(argv: Sequence[str]) -> tuple[list[str], dict[str, Any]]:
    """Accept global machine options before or after subcommands."""
    result: list[str] = []
    options: dict[str, Any] = {}
    takes_value: dict[str, tuple[str, Callable[[str], Any]]] = {
        "--timeout": ("timeout", float),
    }
    forbidden = {"--profile", "--host", "--base-url", "--workspace"}
    index = 0
    while index < len(argv):
        item = argv[index]
        option_name = item.partition("=")[0]
        if option_name in forbidden:
            raise CliError(
                f"{option_name} cannot override the managed Agent Session context",
                USAGE,
                "MANAGED_CONTEXT_OVERRIDE_FORBIDDEN",
            )
        if item == "--json":
            options["json"] = True
            index += 1
            continue
        definition = takes_value.get(item)
        if definition:
            if index + 1 >= len(argv):
                raise CliError(f"{item} requires a value", USAGE, "CLI_USAGE")
            key, converter = definition
            try:
                options[key] = converter(argv[index + 1])
            except ValueError as exc:
                raise CliError(f"Invalid value for {item}", USAGE, "CLI_USAGE") from exc
            index += 2
            continue
        result.append(item)
        index += 1
    return result, options


def _client(runtime: Runtime, args: argparse.Namespace) -> ApiClient:
    return ApiClient(runtime.executor_context(), timeout=args.timeout)


def _confirm(runtime: Runtime, prompt: str, yes: bool) -> None:
    if yes:
        return
    if not getattr(runtime.stdin, "isatty", lambda: False)():
        raise CliError(
            "Confirmation requires Tool Executor approval",
            USAGE,
            "CONFIRMATION_REQUIRED",
        )
    runtime.stderr.write(f"{prompt} [y/N] ")
    runtime.stderr.flush()
    if runtime.stdin.readline().strip().lower() not in {"y", "yes"}:
        raise CliError("Action cancelled", USAGE, "ACTION_CANCELLED")


def _file_upload(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    response = _client(runtime, args).upload_file(args.file_path)
    return CommandResult(response.data, response.request_id)


def _file_list(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    if args.page < 1 or not 1 <= args.limit <= 200:
        raise CliError("page must be >= 1 and limit must be 1..200", USAGE, "CLI_USAGE")
    query = {"page": str(args.page), "limit": str(args.limit)}
    if args.query:
        query["q"] = args.query
    response = _client(runtime, args).request("GET", "/api/files", query=query)
    return CommandResult(response.data, response.request_id)


def _file_get(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    response = _client(runtime, args).request("GET", f"/api/files/{args.file_id}")
    return CommandResult(response.data, response.request_id)


def _file_download(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    client = _client(runtime, args)
    response = client.request("GET", f"/api/files/{args.file_id}/content")
    if response.raw is None:
        raise CliError("Platform did not return file content", 11, "INVALID_FILE_RESPONSE")
    output = write_binary_atomic(
        str(client.context.authorize_file_path(args.output)),
        response.raw,
        force=args.force,
    )
    return CommandResult(
        {
            "file_id": args.file_id,
            "output": str(output),
            "size_bytes": len(response.raw),
            "content_type": response.content_type,
        },
        response.request_id,
    )


def _file_delete(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    client = _client(runtime, args)
    impact = client.request("GET", f"/api/files/{args.file_id}/deletion-impact")
    if not isinstance(impact.data, dict):
        raise CliError("Platform returned invalid deletion impact", 11, "INVALID_FILE_RESPONSE")
    if not impact.data.get("can_delete"):
        raise CliError(
            "File is referenced and cannot be deleted",
            6,
            "FILE_IN_USE",
            impact.data,
            impact.request_id,
        )
    _confirm(runtime, f"Delete file {args.file_id}?", args.yes)
    response = client.request("DELETE", f"/api/files/{args.file_id}")
    return CommandResult({"file_id": args.file_id, "deleted": True}, response.request_id)


def _dispatch_file(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    handlers = {
        "upload": _file_upload,
        "list": _file_list,
        "get": _file_get,
        "download": _file_download,
        "delete": _file_delete,
    }
    return handlers[args.file_command](runtime, args)


def dispatch(runtime: Runtime, args: argparse.Namespace) -> CommandResult:
    if args.root_command == "file":
        return _dispatch_file(runtime, args)
    if args.root_command in DOMAIN_ROOTS:
        return dispatch_domain(runtime, args)
    raise CliError("Unknown business command", USAGE, "CLI_USAGE")


def run(argv: Sequence[str] | None = None, *, runtime: Runtime | None = None) -> int:
    supplied = list(argv if argv is not None else sys.argv[1:])
    json_requested = "--json" in supplied
    active_runtime = runtime or Runtime()
    try:
        cleaned, global_options = _extract_global_options(supplied)
        args = build_parser().parse_args(cleaned)
        for key, value in global_options.items():
            setattr(args, key, value)
        result = dispatch(active_runtime, args)
        envelope = success_envelope(result.data, request_id=result.request_id)
        if getattr(args, "json", False):
            emit_json(envelope, stream=active_runtime.stdout)
        else:
            emit_human(result.data, stream=active_runtime.stdout)
        return result.exit_code
    except CliError as error:
        if json_requested:
            emit_json(error_envelope(error), stream=active_runtime.stdout)
        else:
            active_runtime.stderr.write(f"error: {error.message} [{error.code}]\n")
        return error.exit_code
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 1


def entrypoint() -> None:
    raise SystemExit(run())
