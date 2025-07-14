t = int(input())

for _ in range(t):
    k = int(input())
    digit_length = 1
    count = 9
    start = 1

    while k > digit_length * count:
        k -= digit_length * count
        digit_length += 1
        count *= 10
        start *= 10

    number = start + (k - 1) // digit_length
    digit_index = (k - 1) % digit_length
    print(str(number)[digit_index])
