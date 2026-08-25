import numpy as np
from scipy.stats import norm

def calculate_warrant_price(S, K, T, r, sigma, cvr, option_type='call'):
    """
    Tính giá Warrant bằng mô hình Black-Scholes.
    """
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    
    if option_type == 'call':
        price = (S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)) / cvr
    else:
        price = (K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)) / cvr
    return price

def calculate_warrant_delta(S, K, T, r, sigma, option_type='call'):
    """
    Tính Delta của Warrant bằng mô hình Black-Scholes.
    S: Giá cổ phiếu hiện tại
    K: Giá thực hiện
    T: Thời gian đến khi đáo hạn (tính theo năm)
    r: Lãi suất phi rủi ro (ví dụ: 0.05 cho 5%)
    sigma: Độ biến động (volatility)
    option_type: 'call' hoặc 'put'
    """
    # Tính d1
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    
    if option_type == 'call':
        return norm.cdf(d1)
    else:
        return (norm.cdf(d1) - 1)


def calculate_percent_vega(S, K, T, r, sigma, option_type='call'):
    """
    Tính %Vega dựa trên công thức:
    {[(BS_TheoPrc(T) w.r.t Sigma+0.0001) - (BS_TheoPrc(T) w.r.t Sigma-0.0001)] / 0.02}
    """
    # Sigma (HedgeV) thay đổi +/- 0.0001 (tức là 0.01%)
    vega_up = calculate_warrant_price(S, K, T, r, cvr, sigma + 0.0001, option_type)
    vega_down = calculate_warrant_price(S, K, T, r, cvr, sigma - 0.0001, option_type)
    
    percent_vega = (vega_up - vega_down) / 0.02
    return percent_vega
def calculate_warrant_theta(S, K, T, r, sigma, option_type='call'):
    """
    Tính Theta dựa trên công thức:
    {[(BS_TheoPrc(T)) - (BS_TheoPrc(T) w.r.t max(T-1/365, 0.0001))]}
    Lưu ý: 1 ngày được quy đổi thành 1/365 năm.
    """
    current_price = calculate_warrant_price(S, K, T, r, cvr, sigma, option_type)
    
    # Tính thời gian mới: DTE - 1 ngày (1/365)
    new_T = max(T - (1/365), 0.0001)
    price_at_new_T = calculate_warrant_price(S, K, T, new_T, cvr, sigma, option_type)
    
    theta = current_price - price_at_new_T
    return theta

# Ví dụ sử dụng:
S = 24150    # Giá cổ phiếu hiện tại
K = 25000    # Giá thực hiện
T = 228/365   # 6 tháng còn lại
r = 0.0725   # Lãi suất 5%
sigma = 0.325 # Độ biến động 32,50%
cvr = 4    # Tỷ lệ chuyển đổi

delta_up = calculate_warrant_delta(S*1.0001, K, T, r, sigma, option_type='call')
delta_down = calculate_warrant_delta(S*0.9999, K, T, r, sigma, option_type='call')
delta = calculate_warrant_delta(S, K, T, r, sigma, option_type='call')

balance = 1000000
gamma = (delta_up - delta_down) / 0.0002
dollar_gamma = gamma * S * 0.01 * S * balance
warrant_percent_vega = calculate_percent_vega(S, K, T, r, sigma, option_type='call')
call_price = calculate_warrant_price(S, K, T, r, sigma, cvr, option_type='call')

warrant_theta = calculate_warrant_theta(S, K, T, r, sigma, option_type='call')


print(f'Price of call: {call_price:,.2f}')
print(f"Delta của Warrant (Call): {delta:,.6f}")
print(f"Gamma của Warrant (Call): {gamma:,.6f}")
print(f"Dollar Gamma Impact của Warrant (Call): {dollar_gamma:,.0f}")
print(f"%Vega của Warrant (Call): {warrant_percent_vega:,.8f}")
print(f"Theta của Warrant (Call): {warrant_theta:,.6f}")