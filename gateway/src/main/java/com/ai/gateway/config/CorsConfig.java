package com.ai.gateway.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.reactive.CorsWebFilter;
import org.springframework.web.cors.reactive.UrlBasedCorsConfigurationSource;

@Configuration
public class CorsConfig {

    private final GatewayCorsProperties corsProperties;

    public CorsConfig(GatewayCorsProperties corsProperties) {
        this.corsProperties = corsProperties;
    }

    /********************************************************
     * 跨域（CORS）配置
     * =======================================================
     * 允许所有来源（Origin）访问本网关的所有接口，支持常见的请求方法，
     * 开启跨域凭证支持（Cookies），最大预检缓存时间为 3600 秒。
     * =======================================================
     * !!! 警告：   生产环境请根据实际安全要求调整 AllowedOriginPatterns；
     *     全部放开（*）仅供开发调试，谨慎用于正式环境！
     * @bean 是什么？是Spring Boot中的一个注解，用于将一个方法标注为一个Bean。
     * bean是什么？bean是Spring Boot中的一个对象，用于将一个方法标注为一个Bean。
     ********************************************************/
    @Bean
    public CorsWebFilter corsWebFilter() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOriginPatterns(corsProperties.getAllowedOriginPatterns());
        config.setAllowedMethods(corsProperties.getAllowedMethods());
        config.setAllowedHeaders(corsProperties.getAllowedHeaders());
        config.setAllowCredentials(corsProperties.isAllowCredentials());
        config.setMaxAge(corsProperties.getMaxAge());

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config); // 匹配所有接口
        return new CorsWebFilter(source);
    }
}
