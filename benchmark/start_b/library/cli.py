"""Starting the service from the command line."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from library import db
from library.server import Application, LibraryServer


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="library")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--db", type=Path, required=True)
    options = parser.parse_args(arguments)

    connection = db.open_db(options.db)
    server = LibraryServer(options.port, Application(connection))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        connection.close()
    return 0
