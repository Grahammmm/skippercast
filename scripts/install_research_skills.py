"""Install the three maintained SkipperCast skills in the user's Codex skills folder."""
import argparse
import os
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
NAMES=("skippercast-discover-data","skippercast-ingest-data","skippercast-add-region")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--destination",type=Path,default=Path(os.environ.get("CODEX_HOME",Path.home()/".codex"))/"skills")
    args=p.parse_args()
    args.destination.mkdir(parents=True,exist_ok=True)
    for name in NAMES:
        source=ROOT/"skills"/name;destination=args.destination/name
        if destination.is_symlink(): raise ValueError("Refusing to overwrite a skill symlink")
        if destination.exists() and not (destination/"SKILL.md").is_file():
            raise ValueError("Destination is not a recognizable skill")
        shutil.copytree(source,destination,dirs_exist_ok=True)
        print(destination)


if __name__=="__main__":main()
