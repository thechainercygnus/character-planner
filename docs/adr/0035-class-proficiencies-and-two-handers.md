# 0035: Rules list what the class can use; a two-hander is weighed against both hands

Status: accepted (2026-11-14)

## Context

The Warrior's shipped rules were Protection's: shields only in the off hand and no
two-handers (#93). Fury and Arms Warriors got no off-hand weapons or two-handers unless
they edited the Upgrades settings. Every other class's rules already list what the class
can use (ADR 0023).

The options were rules per spec, picked from the synced talents, or the class's full
proficiencies with the stat weights choosing. Users and shared instances are coming
(#13), and there every character starts from the class defaults. Rules per spec would
mean keeping a spec table per class and guessing for characters without talents yet.

The engine also measured a two-hander against the main hand alone, ignoring the shield or
weapon in the off hand that it replaces. With two-handers allowed, that overrates them.

## Decision

1. **Class proficiencies.**
   - Usage rules list everything the class can use. The Warrior's are:
     - shields and one-hand weapons in the off hand, with Dual Wield from 20;
     - two-handers.
   - Which of these wins is the stat weights' job: a tank preset keeps the shield, and
     Solo DPS picks a two-hander or a second weapon.
2. **Both hands.**
   - A two-hander's gain is its score minus the main hand's and the off hand's.
   - While a two-hander is equipped, nothing is offered for the off hand alone. The swap
     is a one-hander plus that item, and the main hand's list covers the one-hander.
   - A two-hander is recognised by the equipped item's `inventory_type`.
     - `TWOHWEAPON` is Blizzard's usual value. No Forever sample has one yet, so this is
       an assumption to confirm.
3. **Two-handed enchants.** They are advised only for a two-hander in hand, whatever the
   class could wield.
4. **One preset for both DPS specs.** Arms and Fury share the Solo DPS preset for now.
   Revisit it if dual wielding needs a different balance, for example more weight on hit.

## Consequences

- **Your rules:** a Protection Warrior on the tank weights sees no two-handers. Checked on
  the live character's data, at level 19.
- **Fury and Arms:** they need only switch to Solo DPS; the rules need no editing.
- **Edited rules:** rules edited in the app still win (ADR 0016). The new defaults show
  only after Reset.
- **Recommendations beside a two-hander:** a character holding a two-hander gets no
  off-hand suggestions. A one-hander plus a shield shows up as a main-hand row first.
