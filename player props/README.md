# Player props integration

This folder contains the canonical roster resolver and the bookmaker refreshers used by the sports portal.

The Meridian refresher discovers every EuroLeague event from league `208`, finds the `Poeni Igrača` group for each event, and maps player names to the central roster before writing odds. It needs a current `MERIDIAN_ACCESS_TOKEN` from the active meridianbet.rs session; without that variable the existing 1xBet and Superbet refresh remains unchanged.

Runtime databases, captures, logs, tokens and backups stay outside the repository.
