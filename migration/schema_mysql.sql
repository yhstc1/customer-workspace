-- ============================================================
-- 钉钉企业内部小程序 CRM · RDS MySQL 建表脚本（MySQL 8.0）
-- 引擎 InnoDB，字符集 utf8mb4
-- 字段类型对齐原 SQLite；时间戳列保持 TEXT（与原库一致，
-- 由应用层写入本地时间字符串，避免 MySQL CURRENT_TIMESTAMP 的 UTC 时区错位）
-- 用法：在 RDS 控制台 / mysql 客户端执行本文件
-- ============================================================

CREATE DATABASE IF NOT EXISTS crm DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE crm;

SET FOREIGN_KEY_CHECKS = 0;

-- 用户表（手机号注册 + 钉钉免登复用 userId 隔离）
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    password_hash TEXT,
    display_name TEXT,
    is_admin INT DEFAULT 0,
    created_at TEXT,
    status VARCHAR(16) DEFAULT 'active',
    phone VARCHAR(32)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 客户表
CREATE TABLE IF NOT EXISTS customers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    company TEXT,
    phone VARCHAR(255),
    email VARCHAR(255),
    address TEXT,
    latitude DOUBLE,
    longitude DOUBLE,
    category VARCHAR(32) DEFAULT '普通客户',
    priority VARCHAR(16) DEFAULT '中',
    business_type TEXT,
    importance TEXT,
    tier TEXT,
    notes TEXT,
    created_at TEXT,
    updated_at TEXT,
    contact TEXT,
    user_id INT,
    source TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 设置表（复合主键 key + user_id；user_id 可能为哨兵值 0，故不建外键）
CREATE TABLE IF NOT EXISTS settings (
    `key` VARCHAR(128) NOT NULL,
    user_id INT NOT NULL DEFAULT 0,
    value TEXT,
    PRIMARY KEY (`key`, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 事项表
CREATE TABLE IF NOT EXISTS tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(32) DEFAULT '进行中',
    due_date TEXT,
    created_at TEXT,
    updated_at TEXT,
    user_id INT,
    pinned INT DEFAULT 0,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 子待办表
CREATE TABLE IF NOT EXISTS subtasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    done INT DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    order_index INT DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 业务表（合并原 businesses + ledgers）
CREATE TABLE IF NOT EXISTS businesses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT,
    user_id INT,
    company_name TEXT,
    business_type TEXT,
    business_level TEXT,
    number TEXT,
    contract_code TEXT,
    contract_amount DOUBLE,
    start_date TEXT,
    end_date TEXT,
    business_address TEXT,
    date TEXT,
    user_name TEXT,
    parent_id INT,
    business_package TEXT,
    notes TEXT,
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES businesses(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 密码重置申请表
CREATE TABLE IF NOT EXISTS password_resets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    new_password_hash TEXT NOT NULL,
    status VARCHAR(16) DEFAULT 'pending',
    created_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 打卡表
CREATE TABLE IF NOT EXISTS checkins (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    `year_month` VARCHAR(16) NOT NULL,
    count INT DEFAULT 0,
    updated_at TEXT,
    UNIQUE KEY uq_customer_month (customer_id, `year_month`),
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET FOREIGN_KEY_CHECKS = 1;
