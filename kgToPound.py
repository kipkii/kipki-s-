## 1 Kg =  2.20462 pound
## n (kg) = n * 2.20462 (pound)

## 함수
def kg_to_pound():
    ## input에 float 형식으로 숫자 받기, num변수에 추가
    num = float(input("변환할 숫자를 입력하세요.(kg -> pound):"))
    ## 양수일 때
    if num > 0:
        result = num * 2.20462
        print(f'{num}kg는 {result}파운드 입니다')
        return result
    ## 음수일 때
    else: 
        print('양수를 입력하세요')
        return None
        
## 함수 호출 & 결과출력
print(kg_to_pound())