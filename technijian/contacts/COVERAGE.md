# Active Client Contact Coverage

**Generated:** 2026-04-29T10:16:46  
**Source:** `tech-legal/clients/<CODE>/CONTACTS.md` (read-only)

## Resolution policy

**Layer 1 (portal designation):** emails parsed from the portal-designated `Primary Contact`, `Invoice Recipient`, or `Contract Signer` sections of each client's `CONTACTS.md`. This is the authoritative source.

**Layer 2 (contract signer fallback):** when no portal designation is set, the email of the person who signed the most-recent active contract is used, resolved via `GetAllContracts.Signed_DirID` → `stp_Get_All_Dir`. Technijian-internal emails (`@technijian.com`) are excluded — those are Technijian staff who signed as the service provider, not the client contact.

**Not used:** C1/C2/C3 portal roles. These are portal user types, not signing authority. If neither layer resolves a recipient, the client appears in `needs_designation_set.csv` with suggested signer candidates for a portal admin to designate.

## Active-client definition

This repo is for **managed-IT clients** - those with endpoint or DNS security tooling rolled out (Huntress, CrowdStrike, or Umbrella). A client showing CP tickets only with no security signal in 2026-04 is an SEO-only or dev-only relationship managed in a different repo and is **not** considered active here.

**Active for this repo** = at least one of `huntress` / `crowdstrike` / `umbrella` signals observed for 2026-04.

## Roll-up

- Universe: **67** clients in `GET /api/clients/active`
- tech-legal CONTACTS.md files parsed: **71**
- **Managed-IT active for 2026-04: 30** (huntress/crowdstrike/umbrella signal)
- CP-only this month (SEO/dev - not in scope): **7** (see `cp_only_2026-04.csv`)
- Active clients with a tech-legal file: **67 / 67**
- **Operational send list (2026-04)**: managed-IT-active AND send-ready = **20** clients (5 portal-designated, 15 via contract signer) (see `send_list_2026-04.csv`)
- Active but still not send-ready (no designation + no signed contract): **10** (see `needs_designation_set.csv`)
- Active clients with NO tech-legal file: **0** (see `missing_legal.csv`)
- tech-legal entries with no active CP match: **4** (see `stale_legal.csv` - likely terminated)

## Match table

| Code | Client | DirID | Status (2026-04) | Send-ready | Designated | Users |
|---|---|---:|---|---|---|---:|
| AAVA | Aventine at Aliso Viejo Apartments | 6989 | cp,huntress,crowdstrike | yes (contract) | — | 2 |
| ACU | Acuity Advisors | 7139 | cp,huntress,crowdstrike | yes (contract) | — | 23 |
| AFFG | American Fundstars Financial Group LLC | 8141 | cp,huntress,crowdstrike | yes (contract) | — | 2 |
| ALE | Alera Group | 7988 | **none** | **no** | — | 2 |
| ALG | Algro International | 7923 | cp,huntress,crowdstrike | yes (contract) | — | 7 |
| ANI | Andersen Industries, Inc. | 13 | cp,huntress,crowdstrike | yes | yes | 2 |
| AOC | Apartment Association of Orange County | 6270 | cp,huntress,crowdstrike | yes (contract) | — | 18 |
| ASC | Adsys Controls, Inc | 7885 | **none** | **no** | — | 2 |
| AYH | Ayers Hotels | 5976 | **none** | **no** | — | 1 |
| B2I | B2 Insurance | 19 | cp,huntress,crowdstrike | **no** | — | 22 |
| BBC | Burkhart Brothers Construction | 8149 | _cp-only_ | **no** | — | 2 |
| BBE | Boberg Engineering | 8113 | **none** | **no** | — | 2 |
| BBTS | BB Tile and Stone LLC | 5659 | **none** | **no** | — | 1 |
| BRM | Bromic | 5701 | **none** | **no** | — | 6 |
| BST | Boston Group | 6247 | cp,crowdstrike | yes (contract) | — | 66 |
| BWH | Brandywine Homes | 6245 | cp,huntress,crowdstrike | yes (contract) | — | 13 |
| CAM | Coast Aero Mfg | 4307 | **none** | **no** | yes | 3 |
| CBI | Christian Brothers Interiors | 7826 | cp,huntress,crowdstrike | **no** | — | 3 |
| CBL | Chris Bank Law | 5664 | cp,huntress,crowdstrike | **no** | — | 1 |
| CCC | Culp Construction Company | 5914 | cp,huntress,crowdstrike | yes (contract) | — | 35 |
| COB | Core Benefits | 41 | **none** | **no** | yes | 4 |
| CSS | Custom Silicon Solutions | 7093 | _cp-only_ | **no** | — | 2 |
| DTS | Disruptix Talent Solutions | 8052 | cp,huntress,crowdstrike | yes (contract) | — | 2 |
| EAG | Ellis Advisory Group | 6236 | **none** | **no** | — | 1 |
| EBRMD | Ernest B Robinson, MD, PC | 8027 | cp,huntress,crowdstrike | yes (contract) | — | 1 |
| FAL | Law Offices of Stephen Abraham | 5483 | **none** | **no** | — | 1 |
| FOR | Falconer of Redlands | 8066 | _cp-only_ | **no** | — | 2 |
| GRF | Golden Rain Foundation - LWSB | 2709 | **none** | **no** | yes | 6 |
| GSD | GSD Solutions | 7849 | **none** | **no** | — | 1 |
| HHOC | Housing for Health OC | 7280 | cp,huntress,crowdstrike | yes (contract) | — | 4 |
| HIT | Hula IT Services | 7873 | **none** | **no** | — | 1 |
| ICML | ICM Lending | 70 | **none** | **no** | yes | 4 |
| ISI | International Sportsmedicine Institute | 76 | cp,huntress,crowdstrike | yes | yes | 3 |
| JDH | JDH Pacific | 5887 | cp,huntress,crowdstrike | **no** | — | 47 |
| JSD | Jerry Seiner Dealerships | 7958 | huntress | **no** | — | 3 |
| KCC | Kiva Container Corp | 3221 | **none** | **no** | yes | 4 |
| KES | KES Homes | 7930 | cp,huntress,crowdstrike | yes (contract) | — | 1 |
| KRLMD | Kenneth Lynn MD | 86 | **none** | **no** | yes | 2 |
| KSS | Kabuki Springs and Spa | 5110 | cp,huntress,crowdstrike | **no** | — | 4 |
| LAG | Logan Advertising Group | 5883 | **none** | **no** | — | 2 |
| LODC | Law Offices of David Chesley | 8152 | _cp-only_ | **no** | — | 1 |
| MAX | Max Pro Leasing | 5768 | cp,huntress,crowdstrike | **no** | — | 1 |
| MGN | Magnespec | 93 | **none** | **no** | yes | 11 |
| MRM | MiraculousMinds | 7997 | **none** | **no** | — | 2 |
| NOR | Hotel Normandie | 2868 | cp,huntress,crowdstrike | yes | yes | 13 |
| ONE | OneOC | 6130 | **none** | **no** | — | 1 |
| ORX | Ortho Xpress | 108 | cp,huntress,crowdstrike | yes | yes | 150 |
| PCAP | Pet Care Plus | 8138 | _cp-only_ | **no** | — | 1 |
| PCM | 180 Medical, Inc. | 114 | **none** | **no** | yes | 23 |
| PMF | Premed Financial, Inc | 8019 | **none** | **no** | — | 2 |
| RALF | Richard C. Alter Law Firm | 4261 | _cp-only_ | **no** | yes | 1 |
| RBS | Roar Building Services | 6256 | **none** | **no** | — | 1 |
| RKEG | RK Engineering Group, Inc. | 6182 | **none** | **no** | — | 2 |
| RMG | Roddel Marketing Group, Inc | 5779 | huntress,crowdstrike | **no** | — | 3 |
| RSPMD | Rosalina See - Prats M.D. | 129 | cp,huntress,crowdstrike | yes | yes | 2 |
| R_GD | George Dai | 8007 | **none** | **no** | — | 1 |
| SAS | Strategic Air Services | 5985 | cp,huntress,crowdstrike | **no** | — | 20 |
| SGC | Siege Consulting | 7946 | cp,huntress,crowdstrike | yes (contract) | — | 1 |
| SSCI | SSCI, Inc. | 8011 | **none** | **no** | — | 2 |
| STW | STW Autosports | 8123 | **none** | **no** | — | 1 |
| SVE | Saddleback Valley Endodontic | 7296 | **none** | **no** | — | 1 |
| TALY | Talley & Associates | 7728 | cp,huntress,crowdstrike | yes (contract) | — | 1 |
| TOR | Tartan of Redlands | 8063 | _cp-only_ | **no** | — | 2 |
| USFI | USFI Inc. | 5358 | **none** | **no** | — | 1 |
| VAF | Via Auto Finance | 5941 | cp,huntress,crowdstrike,umbrella | **no** | — | 36 |
| VG | Vintage Group | 5839 | cp,huntress,crowdstrike | yes (contract) | — | 3 |
| WCS | West Coast Shipping | 154 | **none** | **no** | yes | 3 |

## Stale tech-legal entries

These have CONTACTS.md files in tech-legal but no matching active CP client. Likely terminated or renamed.

| Code | Name | DirID | Users |
|---|---|---:|---:|
| KEI | Kruger & Eckels, Inc | 7933 | 1 |
| NAC | National Auto Coverage | 5697 | 1 |
| TCH | Torch Enterprises | 7148 | 2 |
| VWC | VisionWise Capital, LLC | — | 0 |
