/**
 * 格式化 ISO 8601 时间字符串为相对时间
 * 
 * @param isoString ISO 8601 格式的时间字符串
 * @returns 相对时间字符串（如 "刚刚"、"3分钟前"、"2小时前"、"3天前" 或日期）
 */
export function formatTime(isoString: string): string {
  // 解析 ISO 8601 字符串
  const date = new Date(isoString);
  
  // 检查日期是否有效
  if (isNaN(date.getTime())) {
    return "未知时间";
  }
  
  const now = Date.now();
  const timestamp = date.getTime();
  const diff = now - timestamp;
  
  // 处理负数情况（未来时间）
  if (diff < 0) {
    return "刚刚";
  }
  
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes}分钟前`;
  if (hours < 24) return `${hours}小时前`;
  if (days < 7) return `${days}天前`;

  return date.toLocaleDateString("zh-CN", {
    month: "short",
    day: "numeric",
  });
}
