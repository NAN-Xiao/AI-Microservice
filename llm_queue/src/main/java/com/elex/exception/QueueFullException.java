package com.elex.exception;

/**
 * 队列已满时抛出的业务异常。
 *
 * <p>Web 层会把该异常转换为 429，提示调用方稍后重试。</p>
 */
public final class QueueFullException extends RuntimeException {
}
