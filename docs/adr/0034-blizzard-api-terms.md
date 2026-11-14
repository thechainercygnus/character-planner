# 0034: What Blizzard's API terms allow us to store and show

Status: accepted (2026-11-13)

## Context

Multiple characters and users (#13), a shared service (#17), a guild view (#18) and a
public character page (#42) all need to know what Blizzard's terms allow before the app
stores or shows anyone else's data (#95). The terms read are:

- the [Blizzard Developer API Terms of Use](https://www.blizzard.com/en-us/legal/a2989b50-5f16-43b1-abec-2ae17cc09dd6/blizzard-developer-api-terms-of-use),
  last updated 1 October 2019, read on 2026-11-13;
- [Forever Companion's developer page](https://forevercompanion.io/developers), read on
  2026-11-13.

This is a reading by the project, not legal advice. Where the terms are silent or
unclear, this record says so and takes the cautious reading.

### Who is bound

Every instance runs with **its own Battle.net client** (`BNET_CLIENT_ID`, the
self-hosting guide). So each operator is a licensee under Blizzard's terms. The project
publishes code that operators run, and its job is to make following the terms the
default.

### What the terms say

| Topic | Where | What it says |
| --- | --- | --- |
| What "Data" is | §1 | Everything the APIs return: data about Blizzard's customers *and* its games, so character profiles and items, recipes and talent trees alike |
| Who may see it | §2, licence grant | Data may go "to end users for their personal use via Your Application." There's no express right to show it to the general public |
| How long it may be kept | §2 item 18 | Refresh at least every 30 days; a maximum 30-day time-to-live for **all** Data; keep it "for no longer than 30 days." For World of Warcraft, a refresh may be done by checking that a character id still exists; if it doesn't, delete that character's data |
| Players opting out | §2 item 18, §11.3 | Data protection law lets players withdraw. If someone asks to stop using their Data (directly, through Blizzard, or by de-linking their account), stop and delete all copies |
| Privacy | §2 item 15, §5 | Post a privacy policy for the Data; tell users if their personal information is stored; never collect a Battle.net password; comply with GDPR and CCPA |
| Attribution | §2 item 13, §4 | Identify Blizzard "clearly and conspicuously" as the source of the Data; no Blizzard trademarks in the app's name or URL; no implied endorsement |
| Money | §2 items 2, 8, 9 | No paid or premium features that use the APIs, no ads in front of them, no selling or licensing Data (aggregate or derived included) |
| Limits | §2 items 16, 17 | 36,000 calls an hour; no scraping outside the APIs |
| A breach | §2 | Tell Blizzard within 24 hours of unauthorised access to the Data |
| Ending | §11.1, §11.2 | When access ends, delete all copies of the Data |
| Derived data | §2 item 8, §9.1 | Blizzard owns derivatives of the APIs. The 30-day rule doesn't say whether data computed from API data counts |

Forever Companion asks for a link back and credit, a cache on our side, and at most 120
requests a minute per IP. Its page states no licence for the data and says nothing about
hosting for many users. It has a feedback form for questions.

## Decision

1. **Kept at most 30 days.** Everything fetched from Blizzard (snapshots, the item
   catalog and icons, recipes, crafted items, talent trees and icons, and stored tokens) is
   deleted once it's 30 days old, and anything still needed is fetched again before then.
   This applies now, for one character, not only from #13. A character Blizzard no
   longer has (a 404 on a refresh) has its data deleted at once.
2. **Derived history is kept small and Blizzard-free where it can be.** The Progress tab
   (ADR 0008) rebuilds history from snapshots. Beyond 30 days it may keep only the
   planner's own numbers: dates, levels, item level, score. It may not keep item names or
   raw responses. Because Blizzard claims derivatives (§9.1), even that is a judgment
   call, recorded here, to revisit if Blizzard says otherwise.
3. **Private display: allowed.** Each user sees their own characters (#13, #14, #15) and,
   with every member's consent, a guild's shared view (#18). That's "end users for their
   personal use."
4. **Public display: not without asking Blizzard first.** A public, Armory-style page
   (#42) isn't clearly covered by "end users for their personal use." #42 stays blocked
   until Blizzard confirms in writing, through the API forum or developer support, that an
   opt-in public page is allowed. If it is, the owner opts in per character, the page
   shows only what the owner chose, and it refreshes and expires on the 30-day rule.
5. **Opting out works everywhere.** A user can remove a character, or their whole
   account, at any time, deleting every copy. The same happens when Blizzard or the
   player asks (§11.3).
6. **Credit and privacy are in the product.**
   - The app names Blizzard as the source of character and game data wherever it shows
     it, beside the Forever Companion credit.
   - Instances ship with a privacy notice saying what's stored, for how long, and how to
     have it removed. Operators can extend it.
   - No Battle.net password is ever handled: the optional login is OAuth.
7. **Never sold.** No paid features, ads or selling of data, for any instance. A shared
   service (#17) runs free.
8. **Forever Companion before a shared service.** Before #17 serves more than a few
   users, ask Forever Companion through its feedback form, and record the answer in #17.

## Consequences

- The single-character app needs changes now, before more features:
  - deleting Blizzard data after 30 days, and slimming the Progress history (#131);
  - crediting Blizzard in the UI (#132);
  - a privacy notice and full deletion (#133). Done: the notice is linked from every
    page's footer, `OPERATOR_CONTACT` names the operator, and the app or
    `character-planner-db erase` deletes every table except the shared game-data caches,
    so a new table is erased unless it's marked shared (docs/privacy.md).
- Progress charts can't show the full item-by-item history beyond 30 days.
- #42 is blocked on a written answer from Blizzard. #13, #17 and #18 can go ahead under
  points 1 to 8.
- If Blizzard's terms change (their date is in the table), this record is revisited.
