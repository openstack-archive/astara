import sys

from akanda.rug.cli import app


def main(args=sys.argv[1:]):
    return app.RugController().run(args)
