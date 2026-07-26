import { Injectable } from '@angular/core';
import { createClient, SupabaseClient } from '@supabase/supabase-js';
import { environment } from '../environments/environment';

export interface Digest {
  id: string;
  category: string;
  label: string;
  digest_html: string;
  num_posts: number;
  num_handles: number;
  lookback_hours: number;
  run_at: string;
}

export interface Post {
  id: string;
  handle: string;
  content: string;
  category: string;
  posted_at: string;
}

@Injectable({ providedIn: 'root' })
export class SupabaseService {
  private client: SupabaseClient;

  constructor() {
    this.client = createClient(
      environment.supabaseUrl,
      environment.supabaseAnonKey
    );
  }

  /** Get the latest digest for each category */
  async getLatestDigests(): Promise<Digest[]> {
    const { data, error } = await this.client
      .from('latest_digests')
      .select('*')
      .order('run_at', { ascending: false });

    if (error) throw error;
    return (data as Digest[]) || [];
  }

  /** Get recent posts for a category */
  async getRecentPosts(category: string, limit = 20): Promise<Post[]> {
    const { data, error } = await this.client
      .from('posts')
      .select('*')
      .eq('category', category)
      .order('posted_at', { ascending: false })
      .limit(limit);

    if (error) throw error;
    return (data as Post[]) || [];
  }

  /** Subscribe to newsletter */
  async subscribe(email: string, categories: string[]): Promise<void> {
    const { error } = await this.client
      .from('subscribers')
      .upsert({ email: email.toLowerCase().trim(), categories, confirmed: false },
               { onConflict: 'email' });

    if (error) throw error;
  }
}
