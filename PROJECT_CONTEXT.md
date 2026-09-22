SPORTS PORTAL — GLAVNI KONTEKST PROJEKTA

Ovaj projekat sam do sada razvijao zajedno sa ChatGPT-om kroz duži niz razgovora. Projekat je već funkcionalan i sadrži dosta stabilnog koda. Zato je najvažnije pravilo:

NE MENJAJ NIJEDAN POSTOJEĆI FAJL DOK PRVO NE PREGLEDAŠ PROJEKAT I NE RAZUMEŠ POSTOJEĆU ARHITEKTURU.

Ne želim veliki refactoring niti prepisivanje delova koji već rade. Radimo malim, kontrolisanim koracima. Pre izmene pregledaj relevantne fajlove, napravi najmanju potrebnu izmenu, zatim testiraj. Ako nešto već radi, ne menjaj ga samo zato što postoji drugačiji način da se napiše.

==================================================
1. KONAČNI CILJ
==================================================

Pravimo pravi javni Sports Portal.

Portal treba da objedini:

1. poređenje kvota više kladionica
2. fudbalske utakmice i statistiku
3. player props
4. EuroLeague statistiku igrača
5. kasnije dodatne sportove i podatke
6. registraciju korisnika
7. besplatan i Premium sadržaj

Ideja je da deo sadržaja bude besplatan, a napredni podaci, dodatne lige i funkcije budu Premium.

Portal nije samo lokalni program. Krajnji cilj je pravi javni web sajt.

Ključni princip arhitekture:

Kladionice / sportski izvori
        ↓
naši kolektori i updateri
        ↓
centralne baze/cache
        ↓
Sports Portal
        ↓
korisnici

KORISNICI JAVNOG SAJTA NE SMEJU SVOJIM KLIKOM DIREKTNO POKRETATI POZIVE KA KLADIONICAMA.

Podaci treba unapred automatski da se prikupljaju i čuvaju, a web portal samo čita naše podatke.

==================================================
2. LOKALNI PROJEKTI
==================================================

Na Windows računaru trenutno postoje četiri glavna foldera:

C:\Users\dkecm\Desktop\sports portal

C:\Users\dkecm\Desktop\kvote

C:\Users\dkecm\Desktop\player props

C:\Users\dkecm\Desktop\fudbal statistika

Nemoj ih premeštati niti menjati njihove putanje bez eksplicitnog dogovora.

Postoje hardkodovane putanje, Task Scheduler zadaci, baze, importi i prečice koji zavise od trenutnih lokacija.

Folderi su odvojeni, ali predstavljaju delove istog budućeg Sports Portala.

==================================================
3. GLAVNI SPORTS PORTAL
==================================================

Glavni portal je:

C:\Users\dkecm\Desktop\sports portal

Glavni Flask fajl:

app.py

Pokretanje:

cd /d "C:\Users\dkecm\Desktop\sports portal"
python app.py

Portal radi na:

http://127.0.0.1:5003

Postojeći portal već ima:

- centralnu /portal stranicu
- login
- registraciju
- session sistem
- Premium status
- fudbalske kvote
- EuroLeague Player Stats integraciju
- druge postojeće funkcionalnosti

EuroLeague je integrisan preko Flask Blueprint-a:

euroleague_portal.py

app.py registruje:

euroleague_bp

Na centralnoj portal stranici postoje kartice za:

Kvote
Fudbal statistika
EuroLeague Player Stats
Premium

Premium koncept trenutno ima pakete:

1 mesec = 600 RSD
3 meseca = 1500 RSD
6 meseci = 2500 RSD

Ovo je razvojni koncept i kasnije će biti proširen pravim payment sistemom.

==================================================
4. FUDBALSKE KLADIONICE
==================================================

Trenutno sistem radi sa 8 kladionica:

BalkanBet
King
MaxBet
Meridian
MerkurXtip
Mozzart
SoccerBet
Superbet

Postoje collector/client fajlovi za kladionice.

football_matcher.py je važan i trenutno stabilan.

NE MENJATI football_matcher.py bez konkretnog razloga.

Postojeća normalizacija timova i matcher logika je rezultat dosta prethodnog rada.

==================================================
5. FUDBALSKI MARKETI
==================================================

Sistem već podržava veliki broj normalizovanih marketa, uključujući:

1X2
DNB
Dupla šansa
Dupla šansa & 2+
Dupla šansa & 0–3
2+ ukupno
3+ ukupno
2+ I ili 2+ II
1+ I & 1+ II
1–3 / 1–3
1–2 / 1–2
1+ I & 2+ ukupno
1+ I & 3+ ukupno
0–1 / 0–2
0–2 / 0–2
1+ I poluvreme
2+ I poluvreme
1+ II poluvreme
2+ II poluvreme
GG
GG I
timske golove po poluvremenima
kombinovane timske markete

Postojeći market mapping je već dosta testiran.

Nemoj menjati postojeće market ključeve i mapping bez potrebe.

==================================================
6. FOOTBALL ODDS DATABASE
==================================================

Glavna nova baza za fudbalske kvote je:

C:\Users\dkecm\Desktop\kvote\football_odds.db

SQLite baza trenutno ima najmanje tabele:

matches

current_odds

matches sadrži podatke kao:

match_id
league
home
away
kickoff_ts
book_ids_json
matched_count
updated_at

current_odds sadrži:

match_id
bookmaker
market_key
selection_key
odd
fetched_at

Primarni koncept current_odds je jedna trenutna vrednost za:

match + bookmaker + market + selection

Trenutno ne pravimo istoriju promena kvota.

Važno sigurnosno pravilo:

Ako bookmaker fetch padne, vrati grešku ili nema kvote, NE SMEJU se obrisati prethodno uspešno sačuvane kvote tog bookmakera.

Bookmakerovi redovi se zamenjuju samo nakon uspešnog non-empty fetch-a.

==================================================
7. AUTOMATSKI FOOTBALL MATCHES UPDATER
==================================================

U folderu:

C:\Users\dkecm\Desktop\kvote

postoji:

football_matches_updater.py

Njegov posao je da periodično:

- pronađe buduće utakmice
- matchuje utakmice između kladionica
- sačuva bookmaker event ID-jeve
- sačuva kickoff vreme
- osveži matches tabelu

Windows Task Scheduler ga automatski pokreće.

Task:

Football Matches Updater

Podešen je da se ponavlja približno svakih 15 minuta.

Task je ručno testiran i radi.

Nemoj ponovo praviti Task Scheduler setup osim ako je eksplicitno potrebno.

==================================================
8. AUTOMATSKI FOOTBALL ODDS UPDATER
==================================================

Postoji poseban Football Odds Updater.

On čita poznate utakmice i bookmaker event ID-jeve iz football_odds.db i automatski osvežava current_odds.

Windows Task Scheduler task:

Football Odds Updater

već postoji i uspešno je testiran.

Arhitektura je:

MATCHER / MATCH UPDATER
        ↓
matches + bookmaker event IDs
        ↓
ODDS UPDATER
        ↓
current_odds
        ↓
Sports Portal

To je arhitektura koju želimo da zadržimo.

==================================================
9. SUPERBET OPTIMIZACIJA
==================================================

Superbet je ranije bio veliki bottleneck.

Pronađen je mnogo brži full-event V2 endpoint.

Logički market identitet kod tog feeda je marketId.

DNB je potvrđen kao marketId 555.

Postojala je testirana V2 transformacija koja flat V2 odds strukturu vraća u oblik kompatibilan sa postojećom normalizacijom.

Ako bude potrebno menjati Superbet deo, prvo pregledaj trenutni superbet.py i postojeći kod.

NE PRETPOSTAVLJAJ da svaki raniji test fajl predstavlja trenutnu produkcionu verziju.

==================================================
10. EUROLEAGUE PLAYER STATS
==================================================

EuroLeague istorijska statistika je već napravljena i radi.

Glavna baza:

C:\Users\dkecm\Desktop\player props\euroleague_stats.db

Čuvamo RAW game-by-game statistiku.

player_games sadrži između ostalog:

season
game_code
player_id
player
team
minutes_seconds
pts
reb
ast
three_pm
two_pm
two_pa
three_pa
ftm
fta
oreb
dreb
steals
turnovers
valuation
plus_minus

PIR je valuation.

Market statistike:

PTS
REB
AST
3PM
P+R
P+A
R+A
PRA
PIR

Prikaz perioda:

L5
L10
SEZONA

L20 je namerno uklonjen iz UI-ja.

Korisnik bira half-point granicu, npr. 18.5.

Sistem računa koliko puta je igrač bio Over/Under te granice.

==================================================
11. EUROLEAGUE SEZONE
==================================================

Podaci se čuvaju po season kodu.

E2025 = sezona 2025/26.

Istorijski podaci NE SMEJU biti prepisani kada dođe nova sezona.

Nove sezone su aditivne.

Season selector treba automatski da čita dostupne sezone iz baze.

Kada postoje E2026 podaci, treba automatski da se pojavi 2026/27.

Ako igrač promeni klub, istorija prethodne sezone ostaje netaknuta.

==================================================
12. EUROLEAGUE UPDATER
==================================================

Postoji:

C:\Users\dkecm\Desktop\player props\euroleague_updater.py

Windows Task Scheduler task:

EuroLeague Updater E2026

pokreće se svakog dana oko 1:00 AM.

Koristi postojeći Python venv iz player props foldera.

Updater:

- proverava official EuroLeague games feed
- nalazi završene utakmice
- proverava koje već postoje u bazi
- preuzima samo nove završene utakmice
- ne pravi duplikate
- čuva stare sezone
- ima delay da ne izaziva 429

Task je testiran i radi.

==================================================
13. PLAYER PROPS
==================================================

Folder:

C:\Users\dkecm\Desktop\player props

Postoji zaseban Flask program koji je ranije radio na:

http://127.0.0.1:5001

Pokretanje:

cd /d "C:\Users\dkecm\Desktop\player props"
venv\Scripts\python.exe app.py

Postojeći NFL Player Props deo ima bookmaker odds/lines za player markets.

Postoje bookmaker collector-i i matcher/name normalization.

NFL kod je već funkcionalan.

NE PREPRAVLJAJ stabilan NFL deo bez konkretnog razloga.

EuroLeague statistika je ranije prvo napravljena u ovom programu, a zatim integrisana u glavni Sports Portal preko posebnog Blueprint-a.

Glavni Sports Portal ne mora da pokreće Player Props Flask server da bi EuroLeague stranica radila.

==================================================
14. EUROLEAGUE BLUEPRINT U SPORTS PORTALU
==================================================

U:

C:\Users\dkecm\Desktop\sports portal

postoji:

euroleague_portal.py

To je Flask Blueprint.

On direktno čita:

C:\Users\dkecm\Desktop\player props\euroleague_stats.db

i ne zavisi od toga da Player Props app radi na portu 5001.

To je namerno.

Nemoj spajati sav EuroLeague kod nazad u veliki app.py.

Želimo modularniju strukturu.

==================================================
15. BACKUP
==================================================

Google Drive for Desktop je instaliran.

Drive je dostupan kao:

G:\

Backup folder:

G:\My Drive\SPORTS PORTAL BACKUP

Postoji:

C:\Users\dkecm\Desktop\sports_portal_backup_v2.py

Windows Task Scheduler task:

Sports Portal Backup

pokreće se svakog dana oko 3:00 AM.

Backup je testiran i radi.

Backup skripta namerno preskače prolazne Chrome/Bet365 cache fajlove koji su ranije pravili grešku pri kopiranju.

Nemoj brisati sports_portal_backup_v2.py jer Task Scheduler trenutno zavisi od njegove putanje.

==================================================
16. VAŽNO O DESKTOP FOLDERIMA
==================================================

Realni projektni folderi su trenutno na Desktopu.

To nije idealno dugoročno, ali ih ZA SADA NE POMERATI.

Postoje hardkodovane putanje i automatizacija koja zavisi od njih.

Kasnije možemo kontrolisano prebaciti sve npr. u:

C:\SportsPortal\

ali tek kada sistematski promenimo:

- hardkodovane putanje
- Task Scheduler
- backup
- shortcuts
- DB paths
- imports

==================================================
17. NAJVAŽNIJI TRENUTNI ZADATAK
==================================================

OVDE SMO STALI.

Glavni Sports Portal app.py još uvek sadrži staru logiku koja pri pokretanju učitava/matchuje mečeve preko bookmaker feedova i koja pri zahtevu za markete može direktno da poziva kladionice.

To sada želimo da promenimo.

CILJ:

Sports Portal više NE treba da kontaktira kladionice kada korisnik otvara utakmicu ili kvote.

Umesto toga:

Sports Portal
        ↓
čita
        ↓
C:\Users\dkecm\Desktop\kvote\football_odds.db

football_matches_updater.py i Football Odds Updater već treba da obavljaju bookmaker komunikaciju u pozadini.

Sports Portal treba da bude reader naše baze.

Prvi sledeći razvojni zadatak je zato:

PREBACITI GLAVNI SPORTS PORTAL DA FUDBALSKE UTAKMICE I KVOTE ČITA IZ football_odds.db, UZ MINIMALNE PROMENE POSTOJEĆEG UI-ja I BEZ KVARA OSTALIH FUNKCIJA.

Pre bilo kakve izmene:

1. pregledaj trenutni:
   C:\Users\dkecm\Desktop\sports portal\app.py

2. pregledaj strukturu:
   C:\Users\dkecm\Desktop\kvote\football_odds.db

3. utvrdi gde app.py trenutno:
   - gradi MATCHES
   - poziva bookmaker collectors
   - koristi ODDS_CACHE
   - koristi load_all_markets
   - vraća /api/markets podatke

4. predloži najmanju bezbednu promenu.

5. NE MENJAJ još kod dok mi prvo ne objasniš šta tačno nameravaš da promeniš.

==================================================
18. PRAVILA RADA ZA CODEX
==================================================

Ovo su obavezna pravila za nastavak projekta:

1. Pregledaj pre izmene.

2. Ne menjaj stabilan kod bez potrebe.

3. Ne radi širok refactoring ako zadatak može da se reši malom izmenom.

4. Jedan mali korak → test → sledeći korak.

5. Pre značajne izmene objasni šta ćeš promeniti.

6. Ne briši istorijske podatke.

7. Ne briši prethodno uspešne bookmaker kvote samo zato što novi fetch nije uspeo.

8. Ne menjaj football_matcher.py bez konkretnog razloga.

9. Ne menjaj stabilni NFL Player Props deo bez konkretnog razloga.

10. Ne spajaj EuroLeague Blueprint nazad u veliki app.py.

11. Ne pomeraj projektne foldere.

12. Ne menjaj Task Scheduler konfiguraciju bez eksplicitnog zahteva.

13. Ne menjaj postojeće DB strukture bez potrebe i bez prethodnog objašnjenja.

14. Ne instaliraj nove biblioteke ako postojeće mogu da urade posao.

15. Ako nisi siguran kako neki postojeći deo radi, prvo ga pregledaj umesto da pretpostaviš.

16. Posle izmene uradi syntax/test proveru gde je moguće.

17. Čuvaj kompatibilnost postojećeg UI-ja i ruta kad god je moguće.

18. Nikada nemoj tretirati testni ili stari fajl kao produkcioni samo zato što postoji u folderu. Prvo utvrdi koji fajl se stvarno koristi.

19. Ako promena može uticati na više delova sistema, prvo objasni posledice.

20. Cilj nije samo da kod trenutno proradi. Gradimo arhitekturu koja će kasnije moći da bude javni Sports Portal sa mnogo korisnika.

==================================================
19. PRVI ZADATAK U OVOM CODEX RAZGOVORU
==================================================

Za sada NEMOJ NIŠTA MENJATI.

Prvo:

- pregledaj source foldere kojima imaš pristup
- pregledaj trenutni Sports Portal app.py
- pronađi postojeću football_odds.db ako joj imaš pristup
- razumi postojeći tok podataka

Zatim mi napiši:

1. šta si pronašao
2. kako Sports Portal trenutno dobija mečeve i kvote
3. kako će izgledati tok kada bude čitao football_odds.db
4. koje tačno delove app.py bi trebalo promeniti
5. koje delove NE treba dirati

Tek nakon moje potvrde menjamo kod.

Takođe napravi u glavnom Sports Portal projektu fajl:

PROJECT_CONTEXT.md

i u njega sačuvaj ovaj kontekst, tako da bude trajna dokumentacija projekta za buduće Codex razgovore.