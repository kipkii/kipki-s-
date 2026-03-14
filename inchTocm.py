## 1 inch = 2.54cm
## n inch = n * 2.54cm

## 함수
def inch_to_cm():
    ## input에 float 형식으로 숫자 받기, num변수에 추가
    num = float(input("변환할 숫자를 입력하세요.(inch -> cm):"))
    ## 양수일 때
    if num > 0:
        result = num * 2.54
        print(f'{num}인치는 {result}센치미터 입니다')
        return result
    ## 음수일 때
    else: 
        print('양수를 입력하세요')
        return None
    
## 함수 호출 & 결과출력
print(inch_to_cm())