package com.ai.gateway.config;

import com.alibaba.cloud.nacos.NacosConfigProperties;
import com.alibaba.nacos.api.NacosFactory;
import com.alibaba.nacos.api.config.ConfigService;
import com.alibaba.nacos.api.config.listener.Listener;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.gateway.event.RefreshRoutesEvent;
import org.springframework.cloud.gateway.route.RouteDefinition;
import org.springframework.cloud.gateway.route.RouteDefinitionRepository;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.ArrayList;
import java.util.List;
import java.util.Properties;
import java.util.concurrent.Executor;

/**
 * 基于 Nacos Config 的动态路由服务。
 * <p>
 * 启动时从 Nacos Config 拉取路由规则 JSON，并监听变更实时刷新。
 * 路由的增删改统一通过 Nacos 控制台操作，不通过 Gateway API。
 */
@Slf4j
@Component
public class NacosDynamicRouteService implements RouteDefinitionRepository {

    private final DynamicRouteProperties props;
    private final NacosConfigProperties nacosConfigProperties;
    private final ApplicationEventPublisher publisher;
    private final ObjectMapper objectMapper = new ObjectMapper();

    private volatile List<RouteDefinition> routes = new ArrayList<>();

    public NacosDynamicRouteService(DynamicRouteProperties props,
                                    NacosConfigProperties nacosConfigProperties,
                                    ApplicationEventPublisher publisher) {
        this.props = props;
        this.nacosConfigProperties = nacosConfigProperties;
        this.publisher = publisher;
    }

    @Override
    public Flux<RouteDefinition> getRouteDefinitions() {
        return Flux.fromIterable(routes);
    }

    /**
     * 路由写入由 Nacos Config 管理，不通过 Gateway API。
     */
    @Override
    public Mono<Void> save(Mono<RouteDefinition> route) {
        return Mono.empty();
    }

    /**
     * 路由删除由 Nacos Config 管理，不通过 Gateway API。
     */
    @Override
    public Mono<Void> delete(Mono<String> routeId) {
        return Mono.empty();
    }

    @PostConstruct
    public void init() {
        try {
            ConfigService configService = buildConfigService();

            String content = configService.getConfig(
                    props.getDataId(), props.getGroup(), props.getTimeoutMs());
            updateRoutes(content, "startup");

            configService.addListener(props.getDataId(), props.getGroup(), new Listener() {
                @Override
                public Executor getExecutor() {
                    return null;
                }

                @Override
                public void receiveConfigInfo(String configInfo) {
                    updateRoutes(configInfo, "nacos-push");
                }
            });

            log.info("[DynamicRoute] Initialized: dataId={}, group={}, routes={}",
                    props.getDataId(), props.getGroup(), routes.size());
        } catch (Exception e) {
            log.error("[DynamicRoute] Failed to init from Nacos Config, gateway will start with EMPTY routes! dataId={}, group={}",
                    props.getDataId(), props.getGroup(), e);
        }
    }

    private void updateRoutes(String content, String source) {
        if (content == null || content.isBlank()) {
            log.warn("[DynamicRoute] Received empty config from Nacos (source={}), routes unchanged", source);
            return;
        }

        try {
            List<RouteDefinition> parsed = objectMapper.readValue(
                    content, new TypeReference<List<RouteDefinition>>() {
                    });
            this.routes = parsed;
            publisher.publishEvent(new RefreshRoutesEvent(this));
            log.info("[DynamicRoute] Routes refreshed (source={}): {} routes loaded", source, parsed.size());
        } catch (Exception e) {
            log.error("[DynamicRoute] Failed to parse route config (source={}), routes unchanged. content={}",
                    source, content, e);
        }
    }

    private ConfigService buildConfigService() throws Exception {
        Properties nacosProps = new Properties();
        nacosProps.put("serverAddr", nacosConfigProperties.getServerAddr());

        String namespace = nacosConfigProperties.getNamespace();
        if (namespace != null && !namespace.isBlank()) {
            nacosProps.put("namespace", namespace);
        }

        String username = nacosConfigProperties.getUsername();
        if (username != null && !username.isBlank()) {
            nacosProps.put("username", username);
        }

        String password = nacosConfigProperties.getPassword();
        if (password != null && !password.isBlank()) {
            nacosProps.put("password", password);
        }

        return NacosFactory.createConfigService(nacosProps);
    }
}
