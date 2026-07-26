import { Component, OnInit, signal, computed } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { SupabaseService, Digest } from './supabase.service';

interface Category {
  id: string;
  label: string;
  color: string;
  icon: string;
}

const CATEGORIES: Category[] = [
  { id: 'analysis',          label: 'Analysis',          color: '#0f3460', icon: '📊' },
  { id: 'company_updates',   label: 'Company Updates',   color: '#1a6b3c', icon: '🏢' },
  { id: 'quarterly_updates', label: 'Quarterly Updates', color: '#7b4a00', icon: '📋' },
  { id: 'macro',             label: 'Macro',             color: '#4a1a7b', icon: '🌐' },
];

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnInit {
  categories = CATEGORIES;
  activeTab = signal<string>('analysis');
  digests = signal<Digest[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);

  // Subscribe form
  subscribeEmail = '';
  subscribeStatus = signal<'idle' | 'loading' | 'success' | 'error'>('idle');
  subscribeMessage = signal('');

  activeDigest = computed(() =>
    this.digests().find(d => d.category === this.activeTab()) ?? null
  );

  activeCategory = computed(() =>
    this.categories.find(c => c.id === this.activeTab()) ?? this.categories[0]
  );

  constructor(
    private supabase: SupabaseService,
    private sanitizer: DomSanitizer,
  ) {}

  ngOnInit() {
    this.loadDigests();
  }

  async loadDigests() {
    try {
      this.loading.set(true);
      this.error.set(null);
      const data = await this.supabase.getLatestDigests();
      this.digests.set(data);
    } catch (err: any) {
      this.error.set('Failed to load digests. Check your Supabase configuration.');
      console.error(err);
    } finally {
      this.loading.set(false);
    }
  }

  setTab(id: string) {
    this.activeTab.set(id);
  }

  getSafeHtml(html: string): SafeHtml {
    return this.sanitizer.bypassSecurityTrustHtml(html);
  }

  getDigestForCategory(id: string): Digest | undefined {
    return this.digests().find(d => d.category === id);
  }

  async subscribe() {
    if (!this.subscribeEmail || !this.subscribeEmail.includes('@')) {
      this.subscribeStatus.set('error');
      this.subscribeMessage.set('Please enter a valid email address.');
      return;
    }
    this.subscribeStatus.set('loading');
    try {
      await this.supabase.subscribe(
        this.subscribeEmail,
        this.categories.map(c => c.id)
      );
      this.subscribeStatus.set('success');
      this.subscribeMessage.set('🎉 You\'re subscribed! Check your inbox to confirm.');
      this.subscribeEmail = '';
    } catch (err: any) {
      this.subscribeStatus.set('error');
      this.subscribeMessage.set('Subscription failed. Please try again.');
    }
  }
}
