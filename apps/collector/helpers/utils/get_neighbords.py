roulette_european_numbers = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
    24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
]

def get_neighbords(num) : 

    if(num == 32) : 
        return [15, 19]
    elif(num == 26) :
        return [3, 35]
    else :
        i = roulette_european_numbers.index(num)
    neighbors_left = roulette_european_numbers[(i - 1) % len(roulette_european_numbers)]
    neighbors_right = roulette_european_numbers[(i + 1) % len(roulette_european_numbers)]

    return [neighbors_left, neighbors_right]

 
     
