"""Scarica un sito (stesso crawl della CLI) e lo salva come fixture di test.

Uso: python scripts/scarica_fixture.py <slug> <url> [mestiere]
"""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onboarding.fetch import HttpFetcher, RegistraFetcher, crawl  # noqa: E402

slug, url = sys.argv[1], sys.argv[2]
mestiere = sys.argv[3] if len(sys.argv) > 3 else "fabbro"
cartella = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / slug
reg = RegistraFetcher(HttpFetcher(), cartella)
avvisi: list[str] = []
pagine = crawl(url, reg, mestiere, avvisi)
reg.salva_manifest({"sito": url, "mestiere": mestiere,
                    "scaricato_il": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")})
print(f"{slug}: {len(pagine)} pagine, avvisi={avvisi}")
for p in pagine:
    print(" ", p.tipo, p.url, len(p.testo))
