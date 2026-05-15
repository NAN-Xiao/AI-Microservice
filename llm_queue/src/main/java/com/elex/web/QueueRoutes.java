package com.elex.web;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.server.RequestPredicate;
import org.springframework.web.reactive.function.server.RouterFunction;
import org.springframework.web.reactive.function.server.RouterFunctions;
import org.springframework.web.reactive.function.server.ServerResponse;

import java.util.regex.Pattern;

/**
 * WebFlux 路由配置。
 *
 * <p>路由层只保留健康检查的快速匹配，其余路径交给请求处理器内部判断。</p>
 */
@Configuration
public class QueueRoutes {
    private static final Pattern HEALTH_PATH = Pattern.compile("^/health/?$");

    /**
     * 注册服务路由。
     *
     * @param handler 请求处理器
     * @return WebFlux 路由函数
     */
    @Bean
    public RouterFunction<ServerResponse> routes(QueueRequestHandler handler) {
        return RouterFunctions.route(pathMatches(HEALTH_PATH), handler::health)
                .andRoute(request -> true, handler::dispatch);
    }

    /**
     * 将路径正则包装成 WebFlux 路由断言。
     *
     * @param pattern 路径匹配正则
     * @return 请求匹配器
     */
    private static RequestPredicate pathMatches(Pattern pattern) {
        return request -> pattern.matcher(request.path()).matches();
    }
}
