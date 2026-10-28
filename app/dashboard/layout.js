import Sidebar from '@/components/studio/Sidebar';
import { StudioProvider } from '@/components/studio/StudioProvider';
import UserBadge from '@/components/studio/UserBadge';

export const metadata = {
  title: 'Dashboard',
};

export default function DashboardLayout({ children }) {
  return (
    <StudioProvider>
      <div className="min-h-screen bg-ink">
        <Sidebar />
        <div className="lg:pl-[264px]">
          <header className="flex justify-end px-5 pt-4 sm:px-8 lg:px-10">
            <UserBadge />
          </header>
          <main className="mx-auto w-full max-w-[1240px] px-5 pb-24 pt-4 sm:px-8 lg:px-10 lg:pt-6">
            {children}
          </main>
        </div>
      </div>
    </StudioProvider>
  );
}
