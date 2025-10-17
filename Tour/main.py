# main.py
from inputs import TRANSPORT_FALLBACK

if TRANSPORT_FALLBACK.lower() == "walk":
    import run_walk
    run_walk.run()
elif TRANSPORT_FALLBACK.lower() == "transit":
    import run_transit
    run_transit.run()
else:
    raise ValueError("TRANSPORT_FALLBACK must be 'walk' or 'transit'")
