# ND-4. Prisijungimas prie brokerio API ir prekybos operacijų vykdymas

**Autorius:** Dominykas Pavlavčius
**Brokeris:** Alpaca (paper trading / demonstracinė sąskaita) · **Kalba:** Python · **Instrumentas:** BTC/USD (keičiamas `config.json`)

## Failai

| Failas | Paskirtis |
|---|---|
| `main.py` | Visa programa (meniu + darbas su Alpaca API) |
| `config.json` | Parametrai: simbolis, kiekis, kryptis, limit kainos nuokrypis, laikotarpis ir kt. |
| `.env.example` | API raktų šablonas (tikri raktai laikomi `.env`, kuris nekeliamas į GitHub) |
| `requirements.txt` | Reikalingos bibliotekos |

## Paleidimas

1. Užsiregistruokite [alpaca.markets](https://alpaca.markets), pasirinkite **Paper Trading** ir sugeneruokite API raktus (**API Keys → Generate New Keys**).
2. Įdiekite bibliotekas:
   ```
   pip install -r requirements.txt
   ```
3. Nukopijuokite `.env.example` į `.env` ir įrašykite savo raktus.
4. Paleiskite:
   ```
   python main.py
   ```

Paleidus programa iš karto prisijungia ir parodo paskyros būseną, tada atidaro meniu:

```
1 - Ryšio ir paskyros patikrinimas
2 - Realaus laiko kainos
3 - Istoriniai duomenys + grafikas
4 - Market pavedimas
5 - Limit pavedimas
6 - Atšaukti pavedimą
7 - Pavedimų būsenos
0 - Išeiti
```

Kiekvienas veiksmas paklausia parametrų. Numatytoji reikšmė rodoma skliaustuose `[ ]` ir paimama iš `config.json`, kai paspaudžiamas Enter.

## Kaip veikia

- **Prisijungimas:** `get_account()` patikrina raktus ir ryšį, parodo paskyros būseną ir ar leidžiama prekiauti kriptovaliutomis.
- **Realaus laiko kainos:** websocket srautas (`CryptoDataStream`). Prie kiekvienos kotiruotės rodomas jos vėlavimas sekundėmis. Jei per nurodytą laiką kotiruočių negaunama, parodomas paskutinis sandoris ir kiek minučių jis vėluoja.
- **Istoriniai duomenys:** `get_crypto_bars()` nurodytam dienų skaičiui ir intervalui (`1Min`, `1Hour`, `1Day`). Grafikas išsaugomas į `istoriniai_BTC-USD.png`.
- **Market / limit pavedimai:** `submit_order()`. Numatytoji limit kaina yra paskutinė kaina −5 % (pirkimui) arba +5 % (pardavimui), kad pavedimas neįvyktų iš karto ir jį būtų galima atšaukti.
- **Atšaukimas:** parodomi neįvykdyti pavedimai, pasirinktas atšaukiamas per `cancel_order_by_id()`, tada parodoma nauja jo būsena.
- **Būsenos:** po kiekvieno veiksmo parodomas brokerio atsakymas, o po `status_wait_seconds` sekundžių būsena perklausiama dar kartą.

### Pavedimų identifikatoriai

IB API reikalauja, kad klientas pats suteiktų kiekvienam pavedimui unikalų, didėjantį ID. Kitą laisvą ID brokeris praneša per `nextValidId`. Alpaca pati suteikia pavedimui ID (UUID), bet leidžia nurodyti ir savo `client_order_id`, kuris turi būti unikalus.

Programa daro tą patį, ką IB `nextValidId`: prisijungdama ji peržiūri brokerio pavedimų istoriją, randa didžiausią savo ID (`DP-ND4-N`) ir kitam pavedimui suteikia `N+1`. Todėl ID nesikartoja ir paleidus programą iš naujo. Kiekvienam pavedimui rodomi abu ID: mūsų (`DP-ND4-5`) ir brokerio (UUID).

## Brokerio apribojimai

- **Kriptovaliutų pavedimai:** leidžiamas tik `gtc` (galioja iki atšaukimo) arba `ioc` galiojimas, todėl `config.json` nustatyta `"time_in_force": "gtc"`. Parduoti (`sell`) galima tik tiek, kiek turima, nes kriptovaliutų skolintis (short) negalima. Maržos (sverto) kriptovaliutoms nėra, todėl perkama tik už grynuosius.
- **Duomenys:** Alpaca kriptovaliutų duomenys (`us` šaltinis) nemokami ir realaus laiko. Prie kiekvienos kotiruotės rodomas jos vėlavimas sekundėmis.
- **Paper trading:** sandoriai simuliuojami, tikri pinigai nenaudojami.

## Veikimo rezultatai

Viskas, kas rodoma ekrane, rašoma ir į `rezultatai.log` (failo vardas keičiamas `config.json`). Šis failas ir grafikas `istoriniai_BTC-USD.png` yra veikimo rezultatai.
