"""Purpose attribution without changing allowance checks or legacy-schema support."""


def reserve(db, amount, ceiling, purpose, *, viewer=False):
    function = 'public.sentra_reserve_viewer_egress' if viewer else 'collector_private.reserve_egress'
    present = db.execute('select to_regprocedure(%s) is not null',
                         (function + '(bigint,bigint,text)',)).fetchone()[0] is True
    if present:
        db.execute(f'select {function}(%s,%s,%s)', (amount, ceiling, purpose))
    else:
        # Only an absent migration selects the old path. Reservation errors never fall back.
        db.execute(f'select {function}(%s,%s)', (amount, ceiling))
