; Test helper: drive the SET pin low, forever.
    set    pindirs, 1
hold0:
    set    pins, 0
    jmp    hold0
