#!/bin/bash

# Agent CA ACME 客户端脚本
# 提供申请新证书和更新证书功能
# 使用方法:
#   ./acme-client.sh new-cert --agent-id <agent_id> [--config <config_file>]
#   ./acme-client.sh renew-cert --agent-id <agent_id> [--config <config_file>]
#   ./acme-client.sh --help

set -euo pipefail

# 默认配置
DEFAULT_CONFIG_FILE="./acme-client.conf"
DEFAULT_CA_SERVER_BASE_URL="http://ca-server:8003/acps-atr-v1"
DEFAULT_CHALLENGE_SERVER_BASE_URL="http://challenge-server:8004/acps-atr-v1"
DEFAULT_CONTACT_EMAIL=""
DEFAULT_KEY_SIZE=2048
DEFAULT_CERT_DIR="./certs"
DEFAULT_PRIVATE_KEY_DIR="./private"

# 日志函数
log_info() {
    echo "[INFO] $(date '+%Y-%m-%d %H:%M:%S'): $*" >&2
}

log_error() {
    echo "[ERROR] $(date '+%Y-%m-%d %H:%M:%S'): $*" >&2
}

log_debug() {
    if [[ "${DEBUG:-false}" == "true" ]]; then
        echo "[DEBUG] $(date '+%Y-%m-%d %H:%M:%S'): $*" >&2
    fi
}

# 显示帮助信息
show_help() {
    cat << EOF
Agent CA ACME 客户端

用法:
    $0 new-cert --agent-id <agent_id> [选项]
    $0 renew-cert --agent-id <agent_id> [选项]
    $0 revoke-cert --agent-id <agent_id> --reason <reason> [选项]
    $0 --help

命令:
    new-cert      申请新证书
    renew-cert    更新现有证书
    revoke-cert   吊销证书

必需参数:
    --agent-id <id>        Agent 标识符 (AIC)

可选参数:
    --config <file>                配置文件路径 (默认: $DEFAULT_CONFIG_FILE)
    --ca-server <url>              CA 服务器基础URL (默认: $DEFAULT_CA_SERVER_BASE_URL)
    --challenge-server <url>       Challenge 服务器基础URL (默认: $DEFAULT_CHALLENGE_SERVER_BASE_URL)
    --contact <email>              联系邮箱
    --key-size <size>              私钥长度 (默认: $DEFAULT_KEY_SIZE)
    --cert-dir <dir>               证书存储目录 (默认: $DEFAULT_CERT_DIR)
    --private-dir <dir>            私钥存储目录 (默认: $DEFAULT_PRIVATE_KEY_DIR)
    --force                        强制操作 (跳过确认)
    --debug                        启用调试模式
    --help                         显示此帮助信息

证书吊销原因 (用于 revoke-cert):
    unspecified           未指定 (0)
    keyCompromise         密钥泄露 (1)
    caCompromise          CA 密钥泄露 (2)
    affiliationChanged    归属变更 (3)
    superseded            已被替代 (4)
    cessationOfOperation  停止操作 (5)

配置文件格式 (acme-client.conf):
    CA_SERVER_BASE_URL=http://ca-server:8003/acps-atr-v1
    CHALLENGE_SERVER_BASE_URL=http://challenge-server:8004/acps-atr-v1
    CONTACT_EMAIL=admin@example.com
    KEY_SIZE=2048
    CERT_DIR=./certs
    PRIVATE_KEY_DIR=./private

示例:
    # 申请新证书
    $0 new-cert --agent-id agent-001-2024-xyz --contact admin@example.com

    # 更新证书
    $0 renew-cert --agent-id agent-001-2024-xyz

    # 吊销证书
    $0 revoke-cert --agent-id agent-001-2024-xyz --reason keyCompromise

EOF
}

# 加载配置文件
load_config() {
    local config_file="$1"
    
    if [[ -f "$config_file" ]]; then
        log_info "加载配置文件: $config_file"
        # shellcheck source=/dev/null
        source "$config_file"
    else
        log_info "配置文件不存在，使用默认配置: $config_file"
    fi
    
    # 设置默认值
    CA_SERVER_BASE_URL="${CA_SERVER_BASE_URL:-$DEFAULT_CA_SERVER_BASE_URL}"
    CHALLENGE_SERVER_BASE_URL="${CHALLENGE_SERVER_BASE_URL:-$DEFAULT_CHALLENGE_SERVER_BASE_URL}"
    CONTACT_EMAIL="${CONTACT_EMAIL:-$DEFAULT_CONTACT_EMAIL}"
    KEY_SIZE="${KEY_SIZE:-$DEFAULT_KEY_SIZE}"
    CERT_DIR="${CERT_DIR:-$DEFAULT_CERT_DIR}"
    PRIVATE_KEY_DIR="${PRIVATE_KEY_DIR:-$DEFAULT_PRIVATE_KEY_DIR}"
}

# 检查依赖
check_dependencies() {
    local deps=("openssl" "curl" "jq" "base64")
    local missing=()
    
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            missing+=("$dep")
        fi
    done
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "缺少依赖工具: ${missing[*]}"
        log_error "请安装缺少的工具后重试"
        exit 1
    fi
}

# 创建目录
ensure_directories() {
    mkdir -p "$CERT_DIR" "$PRIVATE_KEY_DIR"
    
    # 设置私钥目录权限
    chmod 700 "$PRIVATE_KEY_DIR"
}

# 生成账户密钥对
generate_account_key() {
    local account_key_file="$PRIVATE_KEY_DIR/account.key"
    
    if [[ ! -f "$account_key_file" ]]; then
        log_info "生成 ACME 账户密钥..."
        openssl genrsa -out "$account_key_file" "$KEY_SIZE"
        chmod 600 "$account_key_file"
    else
        log_info "使用现有账户密钥: $account_key_file"
    fi
    
    echo "$account_key_file"
}

# 生成证书私钥
generate_cert_key() {
    local agent_id="$1"
    local cert_key_file="$PRIVATE_KEY_DIR/${agent_id}.key"
    
    if [[ ! -f "$cert_key_file" ]]; then
        log_info "生成证书私钥: $cert_key_file"
        openssl genrsa -out "$cert_key_file" "$KEY_SIZE"
        chmod 600 "$cert_key_file"
    else
        log_info "使用现有证书私钥: $cert_key_file"
    fi
    
    echo "$cert_key_file"
}

# 生成 CSR
generate_csr() {
    local agent_id="$1"
    local cert_key_file="$2"
    local csr_file="$CERT_DIR/${agent_id}.csr"
    
    log_info "生成证书签名请求 (CSR): $csr_file"
    
    # 创建临时配置文件
    local openssl_conf=$(mktemp)
    cat > "$openssl_conf" << EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = $agent_id

[v3_req]
keyUsage = keyEncipherment, dataEncipherment, digitalSignature
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = URI:agent://$agent_id
EOF
    
    openssl req -new -key "$cert_key_file" -out "$csr_file" -config "$openssl_conf"
    rm -f "$openssl_conf"
    
    echo "$csr_file"
}

# 获取 JWK thumbprint (按照 RFC 7638)
get_jwk_thumbprint() {
    local account_key_file="$1"
    
    # 获取 RSA 公钥的 n 和 e
    local rsa_info
    rsa_info=$(openssl rsa -in "$account_key_file" -noout -text)
    
    # 提取模数 (n)
    local modulus_hex
    modulus_hex=$(echo "$rsa_info" | awk '/^modulus:/{flag=1; next} /^publicExponent:/{flag=0} flag {print}' | tr -d ' :\n')
    
    # 去除前导零 (如果存在)
    modulus_hex=$(echo "$modulus_hex" | sed 's/^00//')
    
    # 提取指数 (e)
    local exponent_decimal
    exponent_decimal=$(echo "$rsa_info" | grep "publicExponent:" | sed 's/.*publicExponent: \([0-9]*\).*/\1/')
    
    # 将十六进制模数转换为二进制并进行 base64url 编码
    local modulus_b64url
    modulus_b64url=$(echo "$modulus_hex" | xxd -r -p | base64 -w 0 | tr '+/' '-_' | tr -d '=')
    
    # 将十进制指数转换为二进制并进行 base64url 编码
    local exponent_b64url
    # 处理常见的指数值
    if [[ "$exponent_decimal" == "65537" ]]; then
        # 65537 = 0x010001，base64url 编码为 AQAB
        exponent_b64url="AQAB"
    else
        # 通用处理
        local exponent_hex
        exponent_hex=$(printf "%x" "$exponent_decimal")
        # 确保偶数长度
        if (( ${#exponent_hex} % 2 == 1 )); then
            exponent_hex="0$exponent_hex"
        fi
        exponent_b64url=$(echo "$exponent_hex" | xxd -r -p | base64 -w 0 | tr '+/' '-_' | tr -d '=')
    fi
    
    # 创建规范化的 JWK JSON（按字母顺序排序）
    local canonical_jwk="{\"e\":\"$exponent_b64url\",\"kty\":\"RSA\",\"n\":\"$modulus_b64url\"}"
    
    # 计算 SHA256 并进行 base64url 编码
    local thumbprint
    thumbprint=$(echo -n "$canonical_jwk" | sha256sum | cut -d' ' -f1 | xxd -r -p | base64 -w 0 | tr '+/' '-_' | tr -d '=')
    
    echo "$thumbprint"
}

# 获取目录信息
get_directory() {
    local directory_url="$CA_SERVER_BASE_URL/acme/directory"
    
    log_info "获取 ACME 目录信息: $directory_url"
    
    local response
    response=$(curl -s -f "$directory_url" || {
        log_error "无法获取 ACME 目录信息"
        exit 1
    })
    
    echo "$response"
}

# 获取 nonce
get_nonce() {
    local nonce_url="$1"
    
    log_debug "获取 nonce: $nonce_url"
    
    local nonce
    nonce=$(curl -s -I "$nonce_url" | grep -i "replay-nonce:" | cut -d' ' -f2 | tr -d '\r\n')
    
    if [[ -z "$nonce" ]]; then
        log_error "无法获取 nonce"
        exit 1
    fi
    
    echo "$nonce"
}

# 创建 JWS 签名请求
create_jws_request() {
    local account_key_file="$1"
    local url="$2"
    local nonce="$3"
    local payload="$4"
    local account_url="${5:-}"
    
    # 创建 protected header
    local protected_header
    if [[ -n "$account_url" ]]; then
        # 使用 kid (account URL)
        protected_header=$(echo -n "{\"alg\":\"RS256\",\"kid\":\"$account_url\",\"nonce\":\"$nonce\",\"url\":\"$url\"}" | base64 -w 0 | tr '+/' '-_' | tr -d '=')
    else
        # 使用 jwk (首次请求)
        local modulus exponent
        modulus=$(openssl rsa -in "$account_key_file" -noout -modulus | cut -d'=' -f2 | xxd -r -p | base64 -w 0 | tr '+/' '-_' | tr -d '=')
        exponent=$(openssl rsa -in "$account_key_file" -noout -text | grep "publicExponent" | cut -d' ' -f2 | cut -d'(' -f1)
        
        # Convert exponent to base64url
        local exp_hex
        exp_hex=$(printf '%x' "$exponent")
        # Ensure even length for xxd
        if [[ $((${#exp_hex} % 2)) -eq 1 ]]; then
            exp_hex="0$exp_hex"
        fi
        local exp_b64
        exp_b64=$(printf "$exp_hex" | xxd -r -p | base64 -w 0 | tr '+/' '-_' | tr -d '=')
        
        protected_header=$(echo -n "{\"alg\":\"RS256\",\"jwk\":{\"kty\":\"RSA\",\"n\":\"$modulus\",\"e\":\"$exp_b64\"},\"nonce\":\"$nonce\",\"url\":\"$url\"}" | base64 -w 0 | tr '+/' '-_' | tr -d '=')
    fi
    
    # Base64url encode payload
    local encoded_payload
    encoded_payload=$(echo -n "$payload" | base64 -w 0 | tr '+/' '-_' | tr -d '=')
    
    # Create signature
    local signing_input="$protected_header.$encoded_payload"
    local signature
    signature=$(echo -n "$signing_input" | openssl dgst -sha256 -sign "$account_key_file" | base64 -w 0 | tr '+/' '-_' | tr -d '=')
    
    # Create JWS
    echo "{\"protected\":\"$protected_header\",\"payload\":\"$encoded_payload\",\"signature\":\"$signature\"}"
}

# 创建账户
create_account() {
    local directory="$1"
    local account_key_file="$2"
    
    local new_account_url
    new_account_url=$(echo "$directory" | jq -r '.newAccount')
    
    local nonce_url
    nonce_url=$(echo "$directory" | jq -r '.newNonce')
    
    local nonce
    nonce=$(get_nonce "$nonce_url")
    
    log_info "创建 ACME 账户..."
    
    local payload
    if [[ -n "$CONTACT_EMAIL" ]]; then
        payload="{\"termsOfServiceAgreed\":true,\"contact\":[\"mailto:$CONTACT_EMAIL\"]}"
    else
        payload="{\"termsOfServiceAgreed\":true}"
    fi
    
    local jws_request
    jws_request=$(create_jws_request "$account_key_file" "$new_account_url" "$nonce" "$payload")
    
    log_debug "JWS Request: $jws_request"
    log_debug "Nonce used: $nonce"

    local response
    # 发送请求并获取响应头和响应体
    local response_with_headers
    response_with_headers=$(curl -s -i -w "\n%{http_code}" -X POST -H "Content-Type: application/jose+json" -d "$jws_request" "$new_account_url")
    
    local status_code
    status_code=$(echo "$response_with_headers" | tail -n 1)
    
    local headers_and_body
    headers_and_body=$(echo "$response_with_headers" | sed '$d')
    
    local body
    body=$(echo "$headers_and_body" | sed -n '/^$/,$p' | tail -n +2)
    
    if [[ "$status_code" -eq 201 ]] || [[ "$status_code" -eq 200 ]]; then
        # 从响应头中提取location
        local account_url
        account_url=$(echo "$headers_and_body" | grep -i "location:" | cut -d' ' -f2 | tr -d '\r\n')
        
        log_info "账户创建成功: $account_url"
        echo "$account_url"
    elif [[ "$status_code" -eq 409 ]]; then
        # 账户已存在，从响应头中提取location
        local account_url
        account_url=$(echo "$headers_and_body" | grep -i "location:" | cut -d' ' -f2 | tr -d '\r\n')
        
        log_info "使用现有账户: $account_url"
        echo "$account_url"
    else
        log_error "账户创建失败 (HTTP $status_code)"
        log_error "响应: $body"
        exit 1
    fi
}

# 创建订单
create_order() {
    local directory="$1"
    local account_key_file="$2"
    local account_url="$3"
    local agent_id="$4"
    
    local new_order_url
    new_order_url=$(echo "$directory" | jq -r '.newOrder')
    
    local nonce_url
    nonce_url=$(echo "$directory" | jq -r '.newNonce')
    
    local nonce
    nonce=$(get_nonce "$nonce_url")
    
    log_info "创建证书订单: $agent_id"
    
    local payload
    payload="{\"identifiers\":[{\"type\":\"agent\",\"value\":\"$agent_id\"}]}"
    
    local jws_request
    jws_request=$(create_jws_request "$account_key_file" "$new_order_url" "$nonce" "$payload" "$account_url")
    
    local response
    response=$(curl -s -i -w "\n%{http_code}" -X POST -H "Content-Type: application/jose+json" -d "$jws_request" "$new_order_url")
    
    local body_with_headers
    body_with_headers=$(echo "$response" | sed '$d')
    
    local status_code
    status_code=$(echo "$response" | tail -n 1)
    
    if [[ "$status_code" -eq 201 ]]; then
        # 从响应中提取Location头
        local order_url
        order_url=$(echo "$body_with_headers" | grep -i "location:" | cut -d' ' -f2- | tr -d '\r\n')
        
        log_debug "Extracted order_url: '$order_url'"
        
        # 提取JSON body（获取最后一行，通常是JSON）
        local body
        body=$(echo "$body_with_headers" | tail -n 1)
        
        log_debug "Extracted JSON body: '$body'"
        
        log_info "订单创建成功: $order_url"
        echo "$body" | jq -c ". + {\"order_url\": \"$order_url\"}"
    else
        log_error "订单创建失败 (HTTP $status_code)"
        log_error "响应: $body"
        exit 1
    fi
}

# 获取授权信息
get_authorization() {
    local account_key_file="$1"
    local account_url="$2"
    local authz_url="$3"
    local nonce_url="$4"
    
    local nonce
    nonce=$(get_nonce "$nonce_url")
    
    log_info "获取授权信息: $authz_url"
    
    local jws_request
    jws_request=$(create_jws_request "$account_key_file" "$authz_url" "$nonce" "" "$account_url")
    
    local response
    response=$(curl -s -w "\n%{http_code}" -X POST -H "Content-Type: application/jose+json" -d "$jws_request" "$authz_url")
    
    local body
    body=$(echo "$response" | sed '$d')
    
    local status_code
    status_code=$(echo "$response" | tail -n 1)
    
    if [[ "$status_code" -eq 200 ]]; then
        log_info "授权信息获取成功"
        echo "$body"
    else
        log_error "授权信息获取失败 (HTTP $status_code)"
        log_error "响应: $body"
        exit 1
    fi
}

# 处理 HTTP-01 挑战
handle_http01_challenge() {
    local account_key_file="$1"
    local account_url="$2"
    local challenge="$3"
    local agent_id="$4"
    local nonce_url="$5"
    
    local token
    token=$(echo "$challenge" | jq -r '.token')
    
    local challenge_url
    challenge_url=$(echo "$challenge" | jq -r '.url')
    
    # 计算 key authorization
    local jwk_thumbprint
    jwk_thumbprint=$(get_jwk_thumbprint "$account_key_file")
    
    local key_authorization="$token.$jwk_thumbprint"
    
    log_info "处理 HTTP-01 挑战"
    log_info "Token: $token"
    log_info "验证 URL: $CHALLENGE_SERVER_BASE_URL/$agent_id/$token"
    log_info "响应内容: $key_authorization"
    
    if [[ -z "$CHALLENGE_SERVER_BASE_URL" ]]; then
        log_error "未配置 CHALLENGE_SERVER_BASE_URL，无法验证 HTTP-01 挑战"
        log_error "请在配置文件中设置 CHALLENGE_SERVER_BASE_URL 或使用 --challenge-server 参数"
        exit 1
    fi
    
    echo
    echo "=================================================="
    echo "HTTP-01 挑战验证"
    echo "=================================================="
    echo "请确保您的 Challenge Server 在以下 URL 返回指定内容："
    echo
    echo "URL: $CHALLENGE_SERVER_BASE_URL/$agent_id/$token"
    echo "响应内容: $key_authorization"
    echo
    
    # 自动设置挑战响应到Challenge Server
    log_info "正在设置挑战响应到Challenge Server..."
    local set_challenge_url="$CHALLENGE_SERVER_BASE_URL/$agent_id/$token"
    local set_response
    set_response=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Content-Type: text/plain" \
        -d "$key_authorization" \
        "$set_challenge_url" 2>/dev/null)
    
    local set_body="${set_response%$'\n'*}"
    local set_status_code="${set_response##*$'\n'}"
    
    if [[ "$set_status_code" == "200" ]]; then
        log_info "挑战响应设置成功"
    else
        log_error "挑战响应设置失败 (HTTP $set_status_code): $set_body"
        log_error "请手动确保 Challenge Server 能够响应挑战"
    fi
    
    echo "设置完成后按 Enter 键继续..."
    
    if [[ "${FORCE:-false}" != "true" ]]; then
        read -r
    fi
    
    # 验证挑战是否已正确设置
    log_info "验证挑战设置..."
    local verification_url="$CHALLENGE_SERVER_BASE_URL/$agent_id/$token"
    local actual_response
    actual_response=$(curl -s -f "$verification_url" 2>/dev/null || echo "")
    
    if [[ "$actual_response" == "$key_authorization" ]]; then
        log_info "挑战验证设置正确"
    else
        log_error "挑战验证设置不正确"
        log_error "期望响应: $key_authorization"
        log_error "实际响应: $actual_response"
        exit 1
    fi
    
    # 通知 CA 服务器开始验证
    local nonce
    nonce=$(get_nonce "$nonce_url")
    
    log_info "通知 CA 服务器开始验证挑战..."
    log_info "挑战验证URL: $challenge_url"
    
    local jws_request
    jws_request=$(create_jws_request "$account_key_file" "$challenge_url" "$nonce" "{}" "$account_url")
    
    local response
    response=$(curl -s -w "\n%{http_code}" -X POST -H "Content-Type: application/jose+json" -d "$jws_request" "$challenge_url")
    
    local body
    body=$(echo "$response" | sed '$d')
    
    local status_code
    status_code=$(echo "$response" | tail -n 1)
    
    if [[ "$status_code" -eq 200 ]]; then
        log_info "挑战验证请求发送成功"
        
        # 等待验证完成
        local status="pending"
        local attempts=0
        local max_attempts=30
        
        while [[ "$status" == "pending" ]] && [[ $attempts -lt $max_attempts ]]; do
            sleep 2
            attempts=$((attempts + 1))
            
            local nonce2
            nonce2=$(get_nonce "$nonce_url")
            
            local jws_request2
            jws_request2=$(create_jws_request "$account_key_file" "$challenge_url" "$nonce2" "{}" "$account_url")
            
            local response2
            response2=$(curl -s -w "\n%{http_code}" -X POST -H "Content-Type: application/jose+json" -d "$jws_request2" "$challenge_url")
            
            local body2
            body2=$(echo "$response2" | sed '$d')
            
            status=$(echo "$body2" | jq -r '.status')
            
            log_debug "挑战状态: $status (尝试 $attempts/$max_attempts)"
        done
        
        if [[ "$status" == "valid" ]]; then
            log_info "挑战验证成功"
        else
            log_error "挑战验证失败，状态: $status"
            if [[ "$status" == "invalid" ]]; then
                local error_detail
                error_detail=$(echo "$body2" | jq -r '.error.detail // "无详细信息"')
                log_error "错误详情: $error_detail"
            fi
            exit 1
        fi
    else
        log_error "挑战验证请求失败 (HTTP $status_code)"
        log_error "响应: $body"
        exit 1
    fi
}

# 完成订单 (提交 CSR)
finalize_order() {
    local account_key_file="$1"
    local account_url="$2"
    local finalize_url="$3"
    local csr_file="$4"
    local nonce_url="$5"
    
    local nonce
    nonce=$(get_nonce "$nonce_url")
    
    log_info "提交 CSR 完成订单..."
    
    # 读取 CSR 并转换为 DER 格式的 base64url
    local csr_der
    csr_der=$(openssl req -in "$csr_file" -outform DER | base64 -w 0 | tr '+/' '-_' | tr -d '=')
    
    local payload
    payload="{\"csr\":\"$csr_der\"}"
    
    local jws_request
    jws_request=$(create_jws_request "$account_key_file" "$finalize_url" "$nonce" "$payload" "$account_url")
    
    local response
    response=$(curl -s -w "\n%{http_code}" -X POST -H "Content-Type: application/jose+json" -d "$jws_request" "$finalize_url")
    
    local body
    body=$(echo "$response" | sed '$d')
    
    local status_code
    status_code=$(echo "$response" | tail -n 1)
    
    if [[ "$status_code" -eq 200 ]]; then
        log_info "订单完成请求发送成功"
        echo "$body"
    else
        log_error "订单完成失败 (HTTP $status_code)"
        log_error "响应: $body"
        exit 1
    fi
}

# 下载证书
download_certificate() {
    local account_key_file="$1"
    local account_url="$2"
    local certificate_url="$3"
    local agent_id="$4"
    local nonce_url="$5"
    
    log_debug "Download certificate parameters:"
    log_debug "  account_key_file: '$account_key_file'"
    log_debug "  account_url: '$account_url'"  
    log_debug "  certificate_url: '$certificate_url'"
    log_debug "  agent_id: '$agent_id'"
    log_debug "  nonce_url: '$nonce_url'"
    
    # 检查参数是否为空
    if [[ -z "$account_key_file" ]]; then
        log_error "account_key_file is empty"
        return 1
    fi
    if [[ -z "$account_url" ]]; then
        log_error "account_url is empty"
        return 1
    fi
    if [[ -z "$certificate_url" ]]; then
        log_error "certificate_url is empty"
        return 1
    fi
    if [[ -z "$agent_id" ]]; then
        log_error "agent_id is empty"
        return 1
    fi
    if [[ -z "$nonce_url" ]]; then
        log_error "nonce_url is empty"
        return 1
    fi
    
    local nonce
    nonce=$(get_nonce "$nonce_url")
    
    log_debug "Got nonce for certificate download: '$nonce'"
    
    log_info "下载证书..."
    
    local jws_request
    jws_request=$(create_jws_request "$account_key_file" "$certificate_url" "$nonce" "{}" "$account_url")
    
    log_debug "JWS request created for certificate download"
    
    local response
    response=$(curl -s -w "\n%{http_code}" -X POST -H "Content-Type: application/jose+json" -d "$jws_request" "$certificate_url")
    
    local body
    body=$(echo "$response" | sed '$d')
    
    local status_code
    status_code=$(echo "$response" | tail -n 1)
    
    if [[ "$status_code" -eq 200 ]]; then
        local cert_file="$CERT_DIR/${agent_id}.crt"
        echo "$body" > "$cert_file"
        
        log_info "证书下载成功: $cert_file"
        
        # 验证证书
        local subject
        subject=$(openssl x509 -in "$cert_file" -noout -subject -nameopt RFC2253 2>/dev/null || echo "无法解析证书主题")
        
        local validity
        validity=$(openssl x509 -in "$cert_file" -noout -dates 2>/dev/null || echo "无法解析证书有效期")
        
        log_info "证书主题: $subject"
        log_info "证书有效期: $validity"
        
        echo "$cert_file"
    else
        log_error "证书下载失败 (HTTP $status_code)"
        log_error "响应: $body"
        exit 1
    fi
}

# 申请新证书
new_certificate() {
    local agent_id="$1"
    
    log_info "开始申请新证书: $agent_id"
    
    # 生成密钥
    local account_key_file
    account_key_file=$(generate_account_key)
    
    local cert_key_file
    cert_key_file=$(generate_cert_key "$agent_id")
    
    # 生成 CSR
    local csr_file
    csr_file=$(generate_csr "$agent_id" "$cert_key_file")
    
    # 获取目录信息
    local directory
    directory=$(get_directory)
    
    # 创建账户
    local account_url
    account_url=$(create_account "$directory" "$account_key_file")
    
    # 创建订单
    local order
    order=$(create_order "$directory" "$account_key_file" "$account_url" "$agent_id")
    
    log_debug "Order data: $order"
    
    local order_url
    order_url=$(echo "$order" | jq -r '.order_url')
    
    local finalize_url
    finalize_url=$(echo "$order" | jq -r '.finalize')
    
    log_debug "finalize_url: '$finalize_url'"
    
    local certificate_url
    certificate_url=$(echo "$order" | jq -r '.certificate')
    
    # 处理授权和挑战
    local authorizations
    authorizations=$(echo "$order" | jq -r '.authorizations[]')
    
    local nonce_url
    nonce_url=$(echo "$directory" | jq -r '.newNonce')
    
    for authz_url in $authorizations; do
        local authz
        authz=$(get_authorization "$account_key_file" "$account_url" "$authz_url" "$nonce_url")
        
        # 找到 HTTP-01 挑战
        local http01_challenge
        http01_challenge=$(echo "$authz" | jq '.challenges[] | select(.type == "http-01")')
        
        if [[ -n "$http01_challenge" ]]; then
            handle_http01_challenge "$account_key_file" "$account_url" "$http01_challenge" "$agent_id" "$nonce_url"
        else
            log_error "未找到 HTTP-01 挑战"
            exit 1
        fi
    done
    
    # 等待订单状态变为 ready
    log_info "等待订单状态更新..."
    sleep 2
    
    # 完成订单
    local finalized_order
    finalized_order=$(finalize_order "$account_key_file" "$account_url" "$finalize_url" "$csr_file" "$nonce_url")
    
    # 等待证书生成
    local order_status="processing"
    local attempts=0
    local max_attempts=30
    
    while [[ "$order_status" != "valid" ]] && [[ $attempts -lt $max_attempts ]]; do
        sleep 2
        attempts=$((attempts + 1))
        
        local nonce2
        nonce2=$(get_nonce "$nonce_url")
        
        local jws_request
        jws_request=$(create_jws_request "$account_key_file" "$order_url" "$nonce2" "{}" "$account_url")
        
        log_debug "Checking order status curl parameters:"
        log_debug "  jws_request length: ${#jws_request}"
        log_debug "  order_url: '$order_url'"
        
        local response
        response=$(curl -s -w "\n%{http_code}" -X POST -H "Content-Type: application/jose+json" -d "$jws_request" "$order_url")
        
        local body
        body=$(echo "$response" | sed '$d')
        
        order_status=$(echo "$body" | jq -r '.status')
        
        log_debug "订单状态: $order_status (尝试 $attempts/$max_attempts)"
    done
    
    if [[ "$order_status" == "valid" ]]; then
        # 重新获取证书URL（订单完成后才会有）
        log_debug "Order response body for certificate URL extraction: $body"
        local updated_certificate_url
        updated_certificate_url=$(echo "$body" | jq -r '.certificate')
        
        log_debug "Certificate URL from order: '$updated_certificate_url'"
        
        if [[ -z "$updated_certificate_url" || "$updated_certificate_url" == "null" ]]; then
            log_error "证书URL未找到"
            log_debug "Order response body: $body"
            exit 1
        fi
        
        log_debug "Starting certificate download with URL: $updated_certificate_url"
        
        # 下载证书
        local cert_file
        cert_file=$(download_certificate "$account_key_file" "$account_url" "$updated_certificate_url" "$agent_id" "$nonce_url")
        
        log_info "证书申请成功完成"
        log_info "私钥文件: $cert_key_file"
        log_info "证书文件: $cert_file"
        log_info "CSR 文件: $csr_file"
    else
        log_error "订单未能完成，最终状态: $order_status"
        exit 1
    fi
}

# 更新证书 (实际上是申请新证书)
renew_certificate() {
    local agent_id="$1"
    
    log_info "开始更新证书: $agent_id"
    
    # 检查现有证书
    local existing_cert="$CERT_DIR/${agent_id}.crt"
    if [[ -f "$existing_cert" ]]; then
        local expires_at
        expires_at=$(openssl x509 -in "$existing_cert" -noout -enddate | cut -d'=' -f2)
        log_info "当前证书到期时间: $expires_at"
        
        # 检查是否需要更新 (30天内到期)
        if openssl x509 -in "$existing_cert" -checkend $((30 * 24 * 3600)) -noout 2>/dev/null; then
            log_info "证书尚未临近到期，但继续执行更新"
        else
            log_info "证书即将到期，需要更新"
        fi
        
        # 备份现有证书
        local backup_file="$CERT_DIR/${agent_id}.crt.backup.$(date +%s)"
        cp "$existing_cert" "$backup_file"
        log_info "已备份现有证书: $backup_file"
    else
        log_info "未找到现有证书，将申请新证书"
    fi
    
    # 更新证书的过程与申请新证书相同
    new_certificate "$agent_id"
}

# 吊销证书
revoke_certificate() {
    local agent_id="$1"
    local reason="$2"
    
    log_info "开始吊销证书: $agent_id"
    
    # 检查证书文件
    local cert_file="$CERT_DIR/${agent_id}.crt"
    if [[ ! -f "$cert_file" ]]; then
        log_error "证书文件不存在: $cert_file"
        exit 1
    fi
    
    # 转换吊销原因
    local reason_code
    case "$reason" in
        "unspecified") reason_code=0 ;;
        "keyCompromise") reason_code=1 ;;
        "caCompromise") reason_code=2 ;;
        "affiliationChanged") reason_code=3 ;;
        "superseded") reason_code=4 ;;
        "cessationOfOperation") reason_code=5 ;;
        *) 
            log_error "无效的吊销原因: $reason"
            log_error "有效的原因: unspecified, keyCompromise, caCompromise, affiliationChanged, superseded, cessationOfOperation"
            exit 1
            ;;
    esac
    
    # 生成账户密钥
    local account_key_file
    account_key_file=$(generate_account_key)
    
    # 获取目录信息
    local directory
    directory=$(get_directory)
    
    # 创建账户 (如果不存在)
    local account_url
    account_url=$(create_account "$directory" "$account_key_file")
    
    local revoke_cert_url
    revoke_cert_url=$(echo "$directory" | jq -r '.revokeCert')
    
    local nonce_url
    nonce_url=$(echo "$directory" | jq -r '.newNonce')
    
    local nonce
    nonce=$(get_nonce "$nonce_url")
    
    # 读取证书并转换为 DER 格式的 base64url
    local cert_der
    cert_der=$(openssl x509 -in "$cert_file" -outform DER | base64 -w 0 | tr '+/' '-_' | tr -d '=')
    
    local payload
    payload="{\"certificate\":\"$cert_der\",\"reason\":$reason_code}"
    
    log_info "发送证书吊销请求..."
    
    local jws_request
    jws_request=$(create_jws_request "$account_key_file" "$revoke_cert_url" "$nonce" "$payload" "$account_url")
    
    local response
    response=$(curl -s -w "\n%{http_code}" -X POST -H "Content-Type: application/jose+json" -d "$jws_request" "$revoke_cert_url")
    
    local body
    body=$(echo "$response" | sed '$d')
    
    local status_code
    status_code=$(echo "$response" | tail -n 1)
    
    if [[ "$status_code" -eq 200 ]]; then
        log_info "证书吊销成功"
        
        # 移动证书到 revoked 目录
        local revoked_dir="$CERT_DIR/revoked"
        mkdir -p "$revoked_dir"
        
        local revoked_file="$revoked_dir/${agent_id}.crt.revoked.$(date +%s)"
        mv "$cert_file" "$revoked_file"
        
        log_info "已将吊销的证书移动到: $revoked_file"
    else
        log_error "证书吊销失败 (HTTP $status_code)"
        log_error "响应: $body"
        exit 1
    fi
}

# 主函数
main() {
    local command=""
    local agent_id=""
    local config_file="$DEFAULT_CONFIG_FILE"
    local reason=""
    
    # 解析命令行参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            new-cert|renew-cert|revoke-cert)
                command="$1"
                shift
                ;;
            --agent-id)
                agent_id="$2"
                shift 2
                ;;
            --config)
                config_file="$2"
                shift 2
                ;;
            --ca-server)
                CA_SERVER_BASE_URL="$2"
                shift 2
                ;;
            --challenge-server)
                CHALLENGE_SERVER_BASE_URL="$2"
                shift 2
                ;;
            --contact)
                CONTACT_EMAIL="$2"
                shift 2
                ;;
            --key-size)
                KEY_SIZE="$2"
                shift 2
                ;;
            --cert-dir)
                CERT_DIR="$2"
                shift 2
                ;;
            --private-dir)
                PRIVATE_KEY_DIR="$2"
                shift 2
                ;;
            --reason)
                reason="$2"
                shift 2
                ;;
            --force)
                FORCE="true"
                shift
                ;;
            --debug)
                DEBUG="true"
                shift
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                log_error "未知参数: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # 检查命令
    if [[ -z "$command" ]]; then
        log_error "必须指定命令: new-cert, renew-cert, 或 revoke-cert"
        show_help
        exit 1
    fi
    
    # 检查 agent-id
    if [[ -z "$agent_id" ]]; then
        log_error "必须指定 --agent-id 参数"
        show_help
        exit 1
    fi
    
    # 检查 revoke-cert 的 reason 参数
    if [[ "$command" == "revoke-cert" && -z "$reason" ]]; then
        log_error "吊销证书必须指定 --reason 参数"
        show_help
        exit 1
    fi
    
    # 加载配置
    load_config "$config_file"
    
    # 检查依赖
    check_dependencies
    
    # 确保目录存在
    ensure_directories
    
    # 执行命令
    case "$command" in
        new-cert)
            new_certificate "$agent_id"
            ;;
        renew-cert)
            renew_certificate "$agent_id"
            ;;
        revoke-cert)
            revoke_certificate "$agent_id" "$reason"
            ;;
    esac
}

# 如果脚本被直接执行
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
