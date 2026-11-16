; Test helper: pushes 7, 8, 9 to the host, then stops.
    set    x, 7
    mov    isr, x
    push   block
    set    x, 8
    mov    isr, x
    push   block
    set    x, 9
    mov    isr, x
    push   block
done:
    jmp    done
