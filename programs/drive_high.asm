; Test helper: drive the SET pin high, forever.
    set    pindirs, 1
hold1:
    set    pins, 1
    jmp    hold1
