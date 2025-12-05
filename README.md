# MHD-HK

Jednoduchý simulátor linky MHD v Hradci Králové, postavený v Pythonu s využitím knihovny `pygame`. Projekt zobrazuje informační panel autobusu a přehrává hlášení zastávek.

## Požadavky

- Python 3.10+ (doporučeno)
- `pygame`

Instalace závislostí:

```powershell
cd C:\Users\ultron01\Documents\Projekty\BusSimulatorFinal
pip install pygame
```

## Spuštění

```powershell
cd C:\Users\ultron01\Documents\Projekty\BusSimulatorFinal
python .\main.py
```

## Struktura projektu

- `main.py` – hlavní skript se simulátorem.
- `audio/` – složka se zvukovými soubory.
  - `audio/sys/` – systémová hlášení (gong, konečná, bzučák apod.).
  - `audio/stops/` – hlášení jednotlivých zastávek.

## Zvukové soubory a práva

Složka `audio/` není určena k další distribuci bez výslovného písemného souhlasu autora, zejména proto, že obsahuje nahrávky hlasu autora.

- samotná přítomnost těchto souborů v mém repozitáři **neznamená**, že je smíte používat mimo tento projekt,
- je **zakázáno** je nahrávat na jiné repozitáře, sdílet je v jiných projektech nebo je jinak zveřejňovat bez mého výslovného schválení.

Pokud projekt forkujete nebo šíříte, zvažte:

- buď **necommitovat** vlastní zvukové soubory (přidat je do `.gitignore`),
- nebo přiložit jen prázdné/dummy soubory či návod, jak si je uživatel má vytvořit sám.

## Licence

Zdrojový kód je licencovaný pod MIT licencí (viz soubor `LICENSE`). To se **nevztahuje** na audio soubory; ta mohou mít jiný právní režim dle dohody s autorem nahrávek. Hlasové nahrávky v `audio/` nejsou volně licencované a jejich použití mimo tento repozitář bez mého výslovného souhlasu je zakázáno a může vést k právním krokům.
