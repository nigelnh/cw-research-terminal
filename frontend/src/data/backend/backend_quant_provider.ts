import type { QuantProvider, PricingParams, PricingResult, DateRange } from "@/data/providers";
import type { HistoricalVolatilityPoint, BetaPoint } from "@/domain/models";
import { BackendClient, backendClient } from "./backend_client";

export class BackendQuantProvider implements QuantProvider {
  private client: BackendClient;

  constructor(client?: BackendClient) {
    this.client = client || backendClient;
  }

  async calculateGreeks(params: PricingParams): Promise<PricingResult> {
    const raw = await this.client.calculatePricing(params);
    return {
      theoreticalPrice: typeof raw.theoreticalPrice === "number" ? raw.theoreticalPrice : null,
      delta: typeof raw.delta === "number" ? raw.delta : null,
      gamma: typeof raw.gamma === "number" ? raw.gamma : null,
      theta: typeof raw.theta === "number" ? raw.theta : null,
      vega: typeof raw.vega === "number" ? raw.vega : null,
      impliedVolatility: typeof raw.impliedVolatility === "number" ? raw.impliedVolatility : null,
    };
  }

  async getHistoricalVolatility(symbol: string, range?: DateRange): Promise<HistoricalVolatilityPoint[]> {
    const raw = await this.client.getVolatility(symbol, range?.fromDate, range?.toDate);
    return raw.map((r: any) => ({
      symbol: String(r.symbol || symbol).toUpperCase(),
      date: r.date || "",
      hv22: typeof r.hv22 === "number" ? r.hv22 : null,
      hv66: typeof r.hv66 === "number" ? r.hv66 : null,
      hv132: typeof r.hv132 === "number" ? r.hv132 : null,
      hv252: typeof r.hv252 === "number" ? r.hv252 : null,
    }));
  }

  async getBeta(symbol: string, range?: DateRange): Promise<BetaPoint[]> {
    const raw = await this.client.getBeta(symbol, range?.fromDate, range?.toDate);
    return raw.map((r: any) => ({
      symbol: String(r.symbol || symbol).toUpperCase(),
      date: r.date || "",
      beta1m: typeof r.beta1m === "number" ? r.beta1m : (typeof r.beta_1m === "number" ? r.beta_1m : null),
      beta3m: typeof r.beta3m === "number" ? r.beta3m : (typeof r.beta_3m === "number" ? r.beta_3m : null),
      beta12m: typeof r.beta12m === "number" ? r.beta12m : (typeof r.beta_12m === "number" ? r.beta_12m : null),
    }));
  }
}

export const backendQuantProvider = new BackendQuantProvider();
