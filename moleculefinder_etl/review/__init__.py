"""Trust reviews (../TRUST-REVIEWS-PLAN.md): read-only checks of what the site states, run on a schedule on the Mac.

Each review reads the built snapshot, the seeds and (where it says so) the live site, and writes nothing but its own
report. None of them blocks, stops or changes the weekly refresh, the news job or a deploy.
"""
