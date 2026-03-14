import math
## 원주율 * 반지름 *2 (지름) = 원의 길이(원주) 
## 원주율 * 반지름 ^2 = 원의 넓이 
## math.pi를 호출
radius = float(input("반지름 길이를 입력해주세요:"))

def length():
    if radius > 0:
        result = math.pi * (radius * 2)
        print(f"반지름이{radius}인 원의 원주는 약 {result:.2f}입니다.")
        return result
    else:
        print("양수를 입력해주세요")
        return None
    
def area():
    if radius > 0:
        result = math.pi * (radius ** 2)
        print(f"반지름이{radius}인 원의 넓이는 약 {result:.2f}입니다.")
        return result
    else:
        print("양수를 입력해주세요")
        return None


## 함수 호출
length()
area()