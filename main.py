import sys, os

src_dir = os.path.join(os.path.dirname(__file__), "src")
sys.path.append(src_dir)

if __name__ == "__main__":
    from pychronia_storygen.cli import cli
    cli()
