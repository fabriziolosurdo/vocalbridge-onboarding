"""Riga di comando.

    python -m onboarding --sito https://www.esempio.it --mestiere fabbro --out ./out/esempio
    python -m onboarding --sito https://www.esempio.it --gbp ChIJxxxxxxxx --mestiere fabbro --out ./out/esempio
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pipeline, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m onboarding",
                                 description="Estrae i dati di un cliente dal suo sito e/o dalla scheda Google.")
    ap.add_argument("--sito", help="URL del sito del cliente")
    ap.add_argument("--gbp", help="place_id della scheda Google o link Google Maps che lo contiene")
    ap.add_argument("--mestiere", required=True, help="mestiere dichiarato, es. fabbro")
    ap.add_argument("--out", required=True, help="cartella di uscita (ci finiscono dati.json e RAPPORTO.md)")
    ap.add_argument("--fixture", help=argparse.SUPPRESS)  # cartella di fixture: esecuzione offline
    ap.add_argument("--senza-llm", action="store_true", help="non usare lo stadio C anche se la chiave c'è")
    args = ap.parse_args(argv)
    if not args.sito and not args.gbp:
        ap.error("serve almeno uno fra --sito e --gbp")

    fetcher = None
    if args.fixture:
        from .fetch import FixtureFetcher
        fetcher = FixtureFetcher(args.fixture)
    r = pipeline.esegui(args.sito, args.gbp, args.mestiere, fetcher=fetcher, usa_llm=not args.senza_llm)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "dati.json").write_text(r.model_dump_json(indent=2), "utf-8")
    (out / "RAPPORTO.md").write_text(report.genera(r), "utf-8")
    print(f"Scritti {out / 'dati.json'} e {out / 'RAPPORTO.md'} — "
          f"{len(r.pagine_lette)} pagine lette, {len(r.avvisi)} avvisi, campi vuoti: {', '.join(r.campi_vuoti) or 'nessuno'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
