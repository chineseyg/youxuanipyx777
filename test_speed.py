import requests
import time
import re
import os
import subprocess

# CF 官方带宽测试端点 (10MB 随机数据)
TEST_URL = 'https://speed.cloudflare.com/__down?bytes=10485760'  # 10MB
HOST = 'speed.cloudflare.com'
PORT = 443
FILE_SIZE = 10485760  # 字节，用于验证

# 默认端口
DEFAULT_PORT = 8443

# 英文国家名到中文翻译字典 (扩展更多)
EN_TO_CN = {
    'United States': '美国',  # 精确匹配你的 IP
    'Canada': '加拿大',
    'China': '中国',
    'United Kingdom': '英国',
    'Germany': '德国',
    'France': '法国',
    'Japan': '日本',
    'Australia': '澳大利亚',
    'India': '印度',
    'Brazil': '巴西',
    'Russia': '俄罗斯',
    'South Korea': '韩国',
    'Netherlands': '荷兰',
    'Singapore': '新加坡',
    'Hong Kong': '香港',
    'Taiwan': '台湾',
    'Reserved': '预留',
    'Global': '全球',
    'Unknown': '未知'
}

# 浏览器 UA，绕 403
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

def get_chinese_country(ip, max_retries=1):
    """查询 IP 国家（优化：UA + 备用 API + 调试，只重试1次）"""
    headers = {'User-Agent': USER_AGENT}
    for attempt in range(max_retries):
        try:
            # 主 API: ip-api.com
            url = f'https://ip-api.com/json/{ip}?fields=status,country'
            print(f"  查询 {ip} (尝试 {attempt+1}, 主 API)...")
            response = requests.get(url, headers=headers, timeout=10)
            print(f"  Status: {response.status_code}, Text len: {len(response.text)}")
            print(f"  响应预览: {response.text[:50]}...")  # 调试：看错误文本
            
            if response.status_code == 200:
                data = response.json()
                if data['status'] == 'success':
                    en_country = data.get('country', 'Unknown')
                    cn_country = EN_TO_CN.get(en_country, en_country)
                    print(f"  国家: {en_country} -> {cn_country}")
                    return cn_country
                else:
                    print(f"  API fail: {data.get('message', 'Unknown')}")
            elif response.status_code == 403:
                print("  403 疑似 bot 检测/限速，尝试备用 API...")
                # 备用: ipapi.co (免费，限 1000/day，无 UA 严查)
                backup_url = f'https://ipapi.co/{ip}/country_name/'
                backup_resp = requests.get(backup_url, headers=headers, timeout=10)
                if backup_resp.status_code == 200:
                    en_country = backup_resp.text.strip()
                    cn_country = EN_TO_CN.get(en_country, en_country)
                    print(f"  备用成功: {en_country} -> {cn_country}")
                    return cn_country
                else:
                    print(f"  备用也失败: {backup_resp.status_code}")
            else:
                raise ValueError(f"HTTP {response.status_code}")
        
        except Exception as e:
            print(f"  异常 (尝试 {attempt+1}): {e}")
        
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # 指数退避（但 max_retries=1 时无延时）
    
    print(f"  国家查询最终失败 {ip}")
    return '未知'

def test_speed(ip, retries=1):
    """用 curl --resolve 测试 CF 带宽 (MB/s)，重试失败"""
    for attempt in range(retries + 1):
        cmd = [
            'curl', '-s',
            '--resolve', f'{HOST}:{PORT}:{ip}',
            TEST_URL,
            '-o', '/dev/null',
            '-w', 'speed_download:%{speed_download}\nsize:%{size_download}\n',
            '--max-time', '30',
            '--connect-timeout', '10',
            '--retry', '1',
            '--insecure'
        ]
        try:
            print(f" 测试 {ip}:443 (尝试 {attempt+1})...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
            if result.returncode == 0:
                output = result.stdout.strip()
                speed_bps = 0
                downloaded = 0
                for line in output.split('\n'):
                    if line.startswith('speed_download:'):
                        speed_bps = float(line.split(':')[1])
                    elif line.startswith('size:'):
                        downloaded = float(line.split(':')[1])
                if downloaded >= FILE_SIZE * 0.9:
                    speed_mbps = speed_bps / 1048576
                    if speed_mbps > 0:
                        print(f" 成功！下载 {downloaded/1048576:.1f}MB, 速度: {round(speed_mbps, 1)}MB/s")
                        return round(speed_mbps, 1)
                print(f" 下载不完整: {output}")
                return 0.0
            else:
                print(f" curl 失败 (code {result.returncode}): {result.stderr.strip() if result.stderr else 'Timeout'}")
                if attempt < retries:
                    time.sleep(2)
                else:
                    return 0.0
        except subprocess.TimeoutExpired:
            print(f" curl 超时 (30s)")
            return 0.0
        except Exception as e:
            print(f" curl 异常: {e}")
            return 0.0
    return 0.0

def main():
    print("=== 脚本开始运行 ===")
    try:
        if not os.path.exists('ip.txt'):
            print("ip.txt 不存在！")
            return
        with open('ip.txt', 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith('#') and not line.startswith('-')]
        print(f"读取到 {len(lines)} 个 IP")
        if not lines:
            print("ip.txt 中无有效 IP！")
            return
        results = []
        failed_count = 0
        for line in lines:
            match = re.match(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::(\d+))?\s*#(.*)$', line)
            if not match:
                print(f"跳过无效行: {line}")
                continue
            ip = match.group(1)
            port = match.group(2) or str(DEFAULT_PORT)
            ip_port = f"{ip}:{port}"
            cn_country = get_chinese_country(ip)
            print(f"\n测试 {ip_port} - {cn_country}")
            speed = test_speed(ip)
            time.sleep(1)  # 查询+测速延时，防限速
            if speed > 0:
                result = f"{ip_port}#{cn_country} {speed}MB/s"
                results.append(result)
                print(f" -> 成功: {result}")
            else:
                failed_count += 1
                print(f" -> 失败: 连接不通")
        # 写入 speed_ip.txt (按速度降序)
        with open('speed_ip.txt', 'w', encoding='utf-8') as f:
            for res in sorted(results, key=lambda x: float(re.search(r'(\d+\.?\d*)MB/s', x).group(1)), reverse=True):
                f.write(res + '\n')
        print(f"\n完成！共 {len(results)} 个成功 IP 保存到 speed_ip.txt (失败 {failed_count} 个)")
    except Exception as e:
        print(f"脚本异常: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
